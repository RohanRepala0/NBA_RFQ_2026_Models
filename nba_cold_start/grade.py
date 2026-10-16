"""Grading after games are final: CLV, hit rate, Brier, log loss, calibration.

- CLV (prob): close no-vig P(our side at OUR logged line) minus the consensus
  P(our side) when we logged. Positive = the market moved toward us.
- CLV (line): close consensus line minus our line for overs (reversed for
  unders). Positive = the line moved our way.
- Accuracy is scored on model_p and, as the baseline, on consensus_p, both for
  the side we logged. Pushes are excluded.
"""
from __future__ import annotations

import math
from datetime import date

import pandas as pd

from .odds_math import p_over_normal
from .schedule import et_date, et_day_bounds, week_of_season
from .storage import Storage

EPS = 1e-6


def graded_signals(storage: Storage, start: date, end: date) -> pd.DataFrame:
    lo, _ = et_day_bounds(start)
    _, hi = et_day_bounds(end)
    df = storage.query("""
        WITH ev AS (
          SELECT * EXCLUDE (rn) FROM (
            SELECT *, row_number() OVER (PARTITION BY event_id ORDER BY ts DESC) rn FROM events)
          WHERE rn = 1),
        res AS (
          SELECT * EXCLUDE (rn) FROM (
            SELECT *, row_number() OVER (PARTITION BY event_id, player_id ORDER BY ts DESC) rn FROM results)
          WHERE rn = 1)
        SELECT s.*, ev.starts_at, res.actual_points, res.close_consensus_line,
               res.close_consensus_mean, res.close_source
        FROM signals s
        JOIN ev USING (event_id)
        LEFT JOIN res USING (event_id, player_id)
        WHERE ev.starts_at >= ? AND ev.starts_at < ?""", [lo, hi])
    if df.empty:
        return df
    df["game_date"] = df.starts_at.map(et_date)
    df["week"] = df.game_date.map(week_of_season)

    def outcome(r):
        if pd.isna(r.actual_points) or pd.isna(r.line) or pd.isna(r.side):
            return None
        if r.actual_points == r.line:
            return None                                     # push
        won_over = r.actual_points > r.line
        return float(won_over if r.side == "over" else not won_over)

    def clv_p(r):
        if pd.isna(r.close_consensus_mean) or pd.isna(r.line) or pd.isna(r.side) or pd.isna(r.consensus_p):
            return None
        p_over = p_over_normal(r.close_consensus_mean, r.line)
        return (p_over if r.side == "over" else 1 - p_over) - r.consensus_p

    def clv_line(r):
        if pd.isna(r.close_consensus_line) or pd.isna(r.line) or pd.isna(r.side):
            return None
        if r.side == "over":
            return r.close_consensus_line - r.line
        return r.line - r.close_consensus_line

    df["outcome"] = df.apply(outcome, axis=1)
    df["clv_p"] = df.apply(clv_p, axis=1)
    df["clv_line"] = df.apply(clv_line, axis=1)
    return df


def _brier(p: pd.Series, y: pd.Series) -> float:
    return float(((p - y) ** 2).mean())


def _logloss(p: pd.Series, y: pd.Series) -> float:
    p = p.clip(EPS, 1 - EPS)
    return float(-(y * p.map(math.log) + (1 - y) * (1 - p).map(math.log)).mean())


def summarize(df: pd.DataFrame) -> dict:
    out = {"signals": len(df)}
    if df.empty:
        return out
    g = df[df.outcome.notna() & df.model_p.notna() & df.consensus_p.notna()]
    y = g.outcome.astype(float)
    out.update({
        "graded": len(g),
        "pushes_or_missing": int(len(df) - len(g)),
        "hit_rate": float(y.mean()) if len(g) else None,
        "avg_clv_p": float(df.clv_p.dropna().mean()) if df.clv_p.notna().any() else None,
        "avg_clv_line": float(df.clv_line.dropna().mean()) if df.clv_line.notna().any() else None,
        "brier_model": _brier(g.model_p, y) if len(g) else None,
        "brier_market": _brier(g.consensus_p, y) if len(g) else None,
        "logloss_model": _logloss(g.model_p, y) if len(g) else None,
        "logloss_market": _logloss(g.consensus_p, y) if len(g) else None,
    })
    return out


def calibration(df: pd.DataFrame) -> pd.DataFrame:
    g = df[df.outcome.notna() & df.model_p.notna()].copy()
    if g.empty:
        return pd.DataFrame(columns=["bucket", "n", "avg_model_p", "hit_rate"])
    g["bucket"] = (g.model_p * 10).clip(upper=9.999).map(math.floor) / 10
    t = g.groupby("bucket").agg(n=("outcome", "size"), avg_model_p=("model_p", "mean"),
                                hit_rate=("outcome", "mean")).reset_index()
    t["bucket"] = t.bucket.map(lambda b: f"{b:.0%}-{b + 0.1:.0%}")
    return t


def by_segment(df: pd.DataFrame, col: str) -> pd.DataFrame:
    rows = []
    for key, grp in df.groupby(col, dropna=False):
        s = summarize(grp)
        rows.append({col: "unknown" if pd.isna(key) else key, **{k: s.get(k) for k in ("signals", "graded", "hit_rate", "avg_clv_p",
                                                        "brier_model", "brier_market")}})
    return pd.DataFrame(rows)
