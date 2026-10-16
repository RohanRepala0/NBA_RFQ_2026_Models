"""
NBA usage squeeze / vacated-usage model (v0).

Idea: at any moment the five players on the floor use 100% of the team's
possessions, so across a 48-minute game:  sum(USG% x minutes) = 100 x 48 = 4800.
When a roster adds high-usage players (a squeeze) the old usage rates no longer
fit inside that budget; when a star leaves (vacated usage) there is room left over.
We rescale everyone's usage to fit the budget, letting stars hold their share
better than role players, then convert the new usage into a points projection.

Usage:  python usage_model.py [--line "Kawhi Leonard=27.5" ...]
"""
import argparse
import math
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
USAGE_BUDGET = 100 * 48          # percent-minutes per team game

# --- Assumptions (all tunable; document changes) ---------------------------
LEAGUE_AVG_USG = 20.0            # average usage of a player on the floor
STICKINESS_GAMMA = 1.0           # >0: high-usage players resist compression more
EFF_PER_USG_POINT = 0.004        # +0.4% scoring efficiency per usage point given up
SD_FRACTION = 0.30               # game-to-game points SD as a share of the mean
SD_FLOOR = 4.0                   # minimum points SD


def elasticity(usg: float) -> float:
    """How strongly a player's usage moves with the team-wide scale factor."""
    return (LEAGUE_AVG_USG / usg) ** STICKINESS_GAMMA


def solve_scale(usg: pd.Series, mins: pd.Series) -> float:
    """Find k so that sum(usg * k**e * mins) == USAGE_BUDGET (bisection)."""
    e = usg.apply(elasticity)

    def total(k: float) -> float:
        return float((usg * k ** e * mins).sum())

    lo, hi = 0.2, 3.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if total(mid) > USAGE_BUDGET:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def p_over(mean: float, line: float) -> float:
    sd = max(SD_FLOOR, SD_FRACTION * mean)
    z = (line - mean) / sd
    return 0.5 * math.erfc(z / math.sqrt(2))


def project(players: pd.DataFrame, scen: pd.DataFrame, lines: dict) -> pd.DataFrame:
    df = scen.merge(players, on="player", how="left", validate="one_to_one")
    missing = df[df.usg_pct.isna()].player.tolist()
    if missing:
        raise ValueError(f"No usage input for: {missing}")
    if abs(df.proj_mpg.sum() - 240) > 0.5:
        raise ValueError(f"Scenario minutes sum to {df.proj_mpg.sum()}, expected 240")

    raw_demand = float((df.usg_pct * df.proj_mpg).sum())
    k = solve_scale(df.usg_pct, df.proj_mpg)
    df["usg_proj"] = df.usg_pct * k ** df.usg_pct.apply(elasticity)

    has_stats = df.verified.eq("yes") & df.ppg.notna()
    eff = 1 + EFF_PER_USG_POINT * (df.usg_pct - df.usg_proj)
    df["ppg_proj"] = (df.ppg * (df.usg_proj / df.usg_pct)
                      * (df.proj_mpg / df.mpg) * eff).where(has_stats)
    df["fair_line"] = (df.ppg_proj * 2).round() / 2
    df["market_line"] = df.player.map(lines)
    df["p_over_market"] = [
        p_over(m, l) if pd.notna(m) and pd.notna(l) else None
        for m, l in zip(df.ppg_proj, df.market_line)
    ]
    df["budget_pressure_pct"] = round(100 * (raw_demand / USAGE_BUDGET - 1), 1)
    return df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--line", action="append", default=[],
                    help='Market points line, e.g. --line "Kawhi Leonard=27.5"')
    args = ap.parse_args()
    lines = {k.strip(): float(v) for k, v in (s.split("=") for s in args.line)}

    players = pd.read_csv(HERE / "players_2025_26.csv")
    scenarios = pd.read_csv(HERE / "scenarios.csv")

    out = []
    for name, scen in scenarios.groupby("scenario", sort=False):
        res = project(players, scen.drop(columns="scenario"), lines)
        res.insert(0, "scenario", name)
        out.append(res)
        print(f"\n== {name}: usage demand {res.budget_pressure_pct.iloc[0]:+.1f}% vs budget")
        cols = ["player", "proj_mpg", "usg_pct", "usg_proj", "ppg", "ppg_proj",
                "fair_line", "market_line", "p_over_market"]
        print(res[cols].round(2).to_string(index=False))

    result = pd.concat(out, ignore_index=True)
    keep = ["scenario", "player", "team_2025_26", "team_2026_27", "proj_mpg",
            "usg_pct", "usg_proj", "mpg", "ppg", "ppg_proj", "fair_line",
            "market_line", "p_over_market", "budget_pressure_pct", "verified"]
    result[keep].round(2).to_csv(HERE / "projections.csv", index=False)
    print(f"\nWrote {HERE / 'projections.csv'}")


if __name__ == "__main__":
    main()
