"""Fit the efficiency parameters from players who changed context between seasons.

The cross-sectional regression in adjustedTrueShooting (TS% on usage and team
spacing across one season's players) learns that good shooters get the ball.
We need the within-player answer: when one player's usage or spacing changes,
how does his efficiency move? So each row is one player across two seasons:

    ts_new / ts_old - 1 = a * (usg_old - usg_new) + b * (spacing_new - spacing_old) + c

a -> ModelParams.eff_per_usg_point (v0 guess 0.004), b -> ModelParams.spacing_coef
(default 0, off), c absorbs league-wide drift and aging. Weighted least squares
with weight min(minutes_old, minutes_new), so small samples count less.

Input CSV columns: player, usg_old, usg_new, ts_old, ts_new, plus either
spacing_old / spacing_new or team_old / team_new with --teams-old / --teams-new
team shooting tables (the format of data/team_shooting_2025_26.csv), and
optionally min_old / min_new (season minutes).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .spacing import old_context

REQUIRED = ["player", "usg_old", "usg_new", "ts_old", "ts_new"]


def add_spacing_columns(df: pd.DataFrame, teams_old: pd.DataFrame, teams_new: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["spacing_old"] = df.team_old.map(lambda t: old_context(t, teams_old))
    df["spacing_new"] = df.team_new.map(lambda t: old_context(t, teams_new))
    return df


def fit_efficiency(df: pd.DataFrame, min_minutes: float = 500.0) -> dict:
    missing = [c for c in REQUIRED + ["spacing_old", "spacing_new"] if c not in df.columns]
    if missing:
        raise ValueError(f"fit input is missing columns {missing}")
    d = df.dropna(subset=REQUIRED + ["spacing_old", "spacing_new"]).copy()
    if {"min_old", "min_new"} <= set(d.columns):
        d["w"] = d[["min_old", "min_new"]].min(axis=1)
        d = d[d.w >= min_minutes]
    else:
        d["w"] = 1.0
    if len(d) < 10:
        raise ValueError(f"need at least 10 usable player-season pairs, have {len(d)}")

    x = np.column_stack([d.usg_old - d.usg_new, d.spacing_new - d.spacing_old, np.ones(len(d))])
    y = (d.ts_new / d.ts_old - 1).to_numpy()
    sw = np.sqrt(d.w.to_numpy())
    beta, *_ = np.linalg.lstsq(x * sw[:, None], y * sw, rcond=None)
    resid = y - x @ beta
    dof = len(d) - x.shape[1]
    sigma2 = float((d.w.to_numpy() * resid ** 2).sum() / dof)
    cov = sigma2 * np.linalg.inv((x * d.w.to_numpy()[:, None]).T @ x)
    se = np.sqrt(np.diag(cov))
    ybar = np.average(y, weights=d.w)
    r2 = 1 - float((d.w * resid ** 2).sum() / (d.w * (y - ybar) ** 2).sum())
    names = ("eff_per_usg_point", "spacing_coef", "intercept")
    return {"n": int(len(d)), "r2": r2,
            **{k: float(v) for k, v in zip(names, beta)},
            "se": {k: float(v) for k, v in zip(names, se)}}


def describe(result: dict) -> str:
    lines = [f"Fit on {result['n']} player-season pairs (R^2 {result['r2']:.3f})"]
    for k in ("eff_per_usg_point", "spacing_coef", "intercept"):
        v, s = result[k], result["se"][k]
        z = v / s if s else math.inf
        lines.append(f"  {k:18s} {v:+.5f}  (se {s:.5f}, z {z:+.1f})")
    lines.append("Only move these into config.ModelParams if |z| >= 2 and the sign makes sense:")
    lines.append(f"  eff_per_usg_point={result['eff_per_usg_point']:.4f}, spacing_coef={result['spacing_coef']:.5f}")
    return "\n".join(lines)
