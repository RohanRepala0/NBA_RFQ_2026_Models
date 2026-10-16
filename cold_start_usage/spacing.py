"""Team spacing context, adapted from the Adjusted True Shooting idea
(github.com/pravirgoosari/adjustedTrueShooting, BSD-3): spacing combines a
team's 3-point volume and accuracy, each judged against the league.

    z_x     = (x - league_mean) / league_sd       (over the 30 teams, 2025-26)
    spacing = 50 + 10 * (z_3pa + z_3p%) / 2       (50 = league average)

That repo min-max scales each input and takes a geometric mean. On our data
that collapses near the bottom of the league (a projected Toronto 3PA 0.4
below the league minimum scored 0, an 18-point drop), so this uses z-scores,
which stay linear and never clip.

Old context = the player's 2025-26 team (actual team shooting). New context =
the 2026-27 scenario, projected from each player's own 3PA and 3P%, scaled by
his projected minutes and usage. A player traded mid-season ("TOT") gets the
league-average context (50). The model turns the change into a points multiplier
1 + spacing_coef * (new - old); spacing_coef stays 0 until fit.py has
estimated it from real team-changers, so by default spacing is reported, not used.
"""
from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

from .config import TEAM_SHOOTING_CSV

TEAM_COLUMNS = ["team", "fg3a_pg", "fg3_pct", "source"]


def load_team_shooting(path: Path | None = None) -> pd.DataFrame | None:
    path = path or TEAM_SHOOTING_CSV
    if not Path(path).exists():
        return None
    df = pd.read_csv(path)
    missing = [c for c in TEAM_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{path} is missing columns {missing}")
    if df.team.duplicated().any() or df[["fg3a_pg", "fg3_pct"]].isna().any().any():
        raise ValueError(f"{path}: duplicate teams or missing shooting values")
    return df


LEAGUE_AVERAGE = 50.0


def spacing_score(fg3a_pg: float, fg3_pct: float, ref: pd.DataFrame) -> float:
    def z(x: float, col: str) -> float:
        sd = float(ref[col].std(ddof=0))
        return (x - float(ref[col].mean())) / sd if sd > 0 else 0.0
    return LEAGUE_AVERAGE + 10.0 * (z(fg3a_pg, "fg3a_pg") + z(fg3_pct, "fg3_pct")) / 2


def old_context(team: str | None, ref: pd.DataFrame) -> float:
    row = ref[ref.team == team]
    if team is None or (isinstance(team, float) and math.isnan(team)) or row.empty:
        return LEAGUE_AVERAGE
    return spacing_score(float(row.fg3a_pg.iloc[0]), float(row.fg3_pct.iloc[0]), ref)


def projected_team_shooting(df: pd.DataFrame) -> tuple[float | None, float | None, float]:
    """Scenario team 3PA per game and 3P% from player lines.

    `df` needs proj_mpg, mpg, usg_pct, usg_proj, fg3a_pg, fg3_pct. Each player's
    3PA scales with minutes and usage. Returns (3PA, 3P%, minutes coverage).
    """
    have = df.fg3a_pg.notna() & df.mpg.notna() & (df.mpg > 0)
    coverage = float(df.proj_mpg[have].sum() / df.proj_mpg.sum()) if df.proj_mpg.sum() else 0.0
    if not have.any():
        return None, None, coverage
    d = df[have]
    att = d.fg3a_pg * (d.proj_mpg / d.mpg) * (d.usg_proj / d.usg_pct)
    shooters = att > 0
    if not shooters.any():
        return 0.0, None, coverage
    pct = d.fg3_pct.where(d.fg3_pct.notna(), d.fg3_pct.mean())
    team_pct = float((att[shooters] * pct[shooters]).sum() / att[shooters].sum())
    # Scale attempts up to a full 240 minutes if some minutes lack shooting data.
    return float(att.sum() / coverage) if coverage else None, team_pct, coverage
