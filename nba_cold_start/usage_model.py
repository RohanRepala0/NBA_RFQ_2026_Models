"""Usage-squeeze / vacated-usage model, generalized from v0 (see v0/usage_model.py).

Core identity: across a team game the five players on the floor use 100% of
possessions, so sum(USG% x minutes) = 100 x 48 = 4800. Last season's usage
rates are rescaled to fit that budget (stars hold their share better than role
players), then new usage and minutes are converted into a points projection:

    e_i      = (20 / usg_i) ** gamma
    usg_new  = usg_i * k ** e_i,  k solved so sum(usg_new * min_i) = 4800
    ppg_new  = ppg_old * (usg_new / usg_old) * (min_new / min_old)
                       * (1 + 0.004 * (usg_old - usg_new))
                       * (1 + spacing_coef * (spacing_new - spacing_old))
    sd       = max(4, 0.30 * ppg_new)

Spacing (see spacing.py) is computed whenever team shooting data is present;
with spacing_coef = 0 (the default) it is reported but does not move the
projection, so the math is identical to v0.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from . import config
from .config import MODEL, MODEL_VERSION, ModelParams
from .odds_math import points_sd
from .spacing import load_team_shooting, old_context, projected_team_shooting, spacing_score

PLAYER_COLUMNS = ["player", "team_2025_26", "team_2026_27", "usg_pct", "games",
                  "mpg", "ppg", "verified", "source"]
SHOOTING_COLUMNS = ["fg3a_pg", "fg3_pct"]           # optional, needed for spacing
SCENARIO_COLUMNS = ["scenario", "player", "proj_mpg"]


class ModelInputError(ValueError):
    """Inputs the model refuses to run on. Always loud, never silently patched."""


def elasticity(usg, params: ModelParams = MODEL):
    """How strongly a player's usage moves with the team-wide scale factor."""
    return (params.league_avg_usg / usg) ** params.gamma


def solve_scale(usg: pd.Series, mins: pd.Series, params: ModelParams = MODEL,
                lo: float = 0.2, hi: float = 3.0) -> float:
    """Find k so that sum(usg * k**e * mins) == budget (bisection, as in v0)."""
    e = usg.apply(lambda u: elasticity(u, params))

    def total(k: float) -> float:
        return float((usg * k ** e * mins).sum())

    if not total(lo) <= params.usage_budget <= total(hi):
        raise ModelInputError(
            f"Usage budget not reachable for k in [{lo}, {hi}]: "
            f"demand ranges {total(lo):.0f}..{total(hi):.0f} vs {params.usage_budget:.0f}")
    for _ in range(100):
        mid = (lo + hi) / 2
        if total(mid) > params.usage_budget:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def load_players(path: Path | None = None) -> pd.DataFrame:
    path = path or config.PLAYERS_CSV
    df = pd.read_csv(path)
    missing = [c for c in PLAYER_COLUMNS if c not in df.columns]
    if missing:
        raise ModelInputError(f"{path} is missing columns {missing}")
    if df.player.duplicated().any():
        raise ModelInputError(f"Duplicate players in {path}: {df.player[df.player.duplicated()].tolist()}")
    unsourced = df[df.source.isna() | (df.source.astype(str).str.strip() == "")]
    if len(unsourced):
        raise ModelInputError(f"Rows without a source in {path}: {unsourced.player.tolist()}")
    return df


def scenario_path(team: str, scenarios_dir: Path | None = None) -> Path | None:
    """Reviewed minutes (scenarios/TEAM.csv) win over the catalog's auto rotation (scenarios/auto/)."""
    scenarios_dir = scenarios_dir or config.SCENARIOS_DIR
    for path in (scenarios_dir / f"{team}.csv", scenarios_dir / "auto" / f"{team}.csv"):
        if path.exists():
            return path
    return None


def load_scenarios(team: str, scenarios_dir: Path | None = None) -> pd.DataFrame:
    path = scenario_path(team, scenarios_dir)
    if path is None:
        raise ModelInputError(f"No scenarios file for {team} in {scenarios_dir or config.SCENARIOS_DIR}")
    df = pd.read_csv(path)
    missing = [c for c in SCENARIO_COLUMNS if c not in df.columns]
    if missing:
        raise ModelInputError(f"{path} is missing columns {missing}")
    for name, scen in df.groupby("scenario", sort=False):
        validate_minutes(scen, label=f"{team}/{name}")
    return df


def modeled_teams(scenarios_dir: Path | None = None) -> list[str]:
    scenarios_dir = scenarios_dir or config.SCENARIOS_DIR
    teams = {p.stem for p in scenarios_dir.glob("*.csv")} | {p.stem for p in scenarios_dir.glob("auto/*.csv")}
    return sorted(teams - set(config.CATALOG_EXCLUDED_TEAMS))


def validate_minutes(scen: pd.DataFrame, params: ModelParams = MODEL, label: str = "scenario") -> None:
    dupes = scen.player[scen.player.duplicated()].tolist()
    if dupes:
        raise ModelInputError(f"{label}: duplicate players {dupes}")
    if scen.proj_mpg.isna().any() or (scen.proj_mpg < 0).any():
        raise ModelInputError(f"{label}: minutes must be present and non-negative")
    total = float(scen.proj_mpg.sum())
    if abs(total - params.minutes_total) > params.minutes_tolerance:
        raise ModelInputError(f"{label}: scenario minutes sum to {total:g}, expected {params.minutes_total:g}")


def project_scenario(players: pd.DataFrame, scen: pd.DataFrame,
                     params: ModelParams = MODEL,
                     team_shooting: pd.DataFrame | None = None) -> pd.DataFrame:
    """Project one scenario. `scen` has columns player, proj_mpg (scenario column optional).

    Pass `team_shooting` (see spacing.load_team_shooting) to add spacing columns.
    """
    scen = scen[[c for c in scen.columns if c != "scenario"]]
    validate_minutes(scen, params)
    df = scen.merge(players, on="player", how="left", validate="one_to_one")
    missing = df[df.usg_pct.isna()].player.tolist()
    if missing:
        raise ModelInputError(f"No usage input for: {missing}")

    raw_demand = float((df.usg_pct * df.proj_mpg).sum())
    k = solve_scale(df.usg_pct, df.proj_mpg, params)
    df["usg_proj"] = df.usg_pct * k ** df.usg_pct.apply(lambda u: elasticity(u, params))

    has_stats = df.verified.eq("yes") & df.ppg.notna() & df.mpg.notna()
    eff = 1 + params.eff_per_usg_point * (df.usg_pct - df.usg_proj)
    add_spacing(df, team_shooting, params)
    df["ppg_proj"] = (df.ppg * (df.usg_proj / df.usg_pct)
                      * (df.proj_mpg / df.mpg) * eff * df.spacing_mult).where(has_stats)
    df["sd_proj"] = df.ppg_proj.map(lambda m: points_sd(m, params) if pd.notna(m) else float("nan"))
    df["fair_line"] = (df.ppg_proj * 2).round() / 2
    df["budget_pressure_pct"] = round(100 * (raw_demand / params.usage_budget - 1), 1)
    df["scale_k"] = k
    # Unknown when last season's team is missing (placeholder rows).
    df["new_team"] = df.team_2025_26.ne(df.team_2026_27).astype(object).where(df.team_2025_26.notna(), None)
    return df


def add_spacing(df: pd.DataFrame, ref: pd.DataFrame | None, params: ModelParams = MODEL) -> None:
    """Adds spacing_old, spacing_new, spacing_delta, spacing_mult (in place)."""
    df["spacing_old"] = df["spacing_new"] = df["spacing_delta"] = float("nan")
    df["spacing_mult"] = 1.0
    if ref is None or not set(SHOOTING_COLUMNS) <= set(df.columns):
        return
    fg3a, fg3_pct, coverage = projected_team_shooting(df)
    if fg3a is None or fg3_pct is None or pd.isna(fg3a) or pd.isna(fg3_pct) \
            or coverage < params.spacing_min_coverage:
        return
    new = spacing_score(fg3a, fg3_pct, ref)
    df["spacing_new"] = new
    df["spacing_old"] = df.team_2025_26.map(lambda t: old_context(t, ref))
    df["spacing_delta"] = df.spacing_new - df.spacing_old
    # A missing context never blanks a projection: no spacing info means no adjustment.
    df["spacing_mult"] = (1 + params.spacing_coef * df.spacing_delta).fillna(1.0)


def project_team(team: str, players: pd.DataFrame | None = None,
                 scenarios_dir: Path | None = None, params: ModelParams = MODEL,
                 team_shooting: pd.DataFrame | None = None) -> pd.DataFrame:
    """All scenarios for one team, stacked, with a `scenario` column first."""
    players = load_players() if players is None else players
    team_shooting = load_team_shooting() if team_shooting is None else team_shooting
    scenarios = load_scenarios(team, scenarios_dir)
    out = []
    for name, scen in scenarios.groupby("scenario", sort=False):
        res = project_scenario(players, scen, params, team_shooting)
        res.insert(0, "scenario", name)
        res.insert(1, "team", team)
        out.append(res)
    return pd.concat(out, ignore_index=True)


def inputs_hash(players: pd.DataFrame, scen: pd.DataFrame, params: ModelParams = MODEL) -> str:
    """Stable hash of every input that can move a projection."""
    names = set(scen.player)
    rows = players[players.player.isin(names)].sort_values("player")
    cols = PLAYER_COLUMNS + [c for c in SHOOTING_COLUMNS if c in rows.columns]
    payload = {
        "players": json.loads(rows[cols].to_json(orient="records")),
        "scenario": json.loads(scen.sort_values("player")[["player", "proj_mpg"]].to_json(orient="records")),
        "params": params.__dict__,
        "model_version": MODEL_VERSION,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
