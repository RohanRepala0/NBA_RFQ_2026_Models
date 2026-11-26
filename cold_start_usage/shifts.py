"""Role shifts: where this season's box scores already disagree with last season's numbers.

Early-season usage and shot-mix changes mostly keep their direction (a player on a new team, a
vacated role), and the model leans on last season until the evidence piles up. This lists, per
player with enough minutes, this season's usage, minutes, points and threes attempts per 36 and
3PA share against last season's (data/players_2025_26.csv), and how far the rolling model's shrunk
usage has moved (features.py): `gap` is what the shrinkage still holds back.

A shift is flagged when it is big for its stat (config.SHIFT_FLAGS) on at least
config.SHIFT_MIN_MINUTES minutes. Facts about past games only; the projections stay the model's.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config
from .features import history, player_features, player_prior, prior_rates, league_rates
from .players import name_key
from .storage import Storage


def shifts(storage: Storage, before, players: pd.DataFrame) -> pd.DataFrame:
    """One row per player who played this season before `before` (box scores of earlier ET dates)."""
    box, _ = history(storage, before)
    if box.empty:
        return pd.DataFrame()
    box = box[box.minutes.notna() & (box.minutes > 0)]
    priors = prior_rates(players)
    league = league_rates(box, priors)
    named = priors.assign(name=priors.player)
    by_id = {pid: r for pid, r in named.set_index("sgo_player_id").iterrows() if isinstance(pid, str) and pid}
    by_key = {name_key(n): r for n, r in named.set_index("player").iterrows()}
    shooting = players.set_index("player")
    rows = []
    for pid, g in box.groupby("player_id"):
        name, team = g.player_name.iloc[0], g.sort_values("starts_at").team.iloc[-1]
        prior_row = by_id.get(pid)
        if prior_row is None:
            prior_row = by_key.get(name_key(name))
        mins = float(g.minutes.sum())
        u = g[g.usg_pct.notna()]
        usg_now = float(np.average(u.usg_pct, weights=u.minutes)) if len(u) else np.nan
        fga, fg3a = float(g.fga.sum()), float(g.fg3a.sum())
        prior = player_prior(prior_row, league, team, float(g.minutes.mean()))
        shrunk = player_features(g.sort_values("starts_at", ascending=False), prior)["usg"]
        last = prior_row["name"] if prior_row is not None else None
        prior_fg3a36 = (36 * shooting.at[last, "fg3a_pg"] / shooting.at[last, "mpg"]
                        if last in shooting.index and shooting.at[last, "mpg"] > 0 else np.nan)
        prior_pts36 = 36 * prior.rates["points"]
        rows.append({
            "player_id": pid, "player": name, "team": team, "team_2025_26": None if prior_row is None else prior_row.team_2025_26,
            "new_team": prior.new_team, "has_prior": prior.has_row, "games": len(g), "minutes": round(mins, 1),
            "mpg": round(mins / len(g), 1), "mpg_prior": round(prior.mpg, 1),
            "usg": round(usg_now, 1), "usg_prior": round(prior.usg, 1), "usg_model": round(shrunk, 1),
            "pts36": round(36 * float(g.pts.sum()) / mins, 1), "pts36_prior": round(prior_pts36, 1),
            "fg3a36": round(36 * fg3a / mins, 1), "fg3a36_prior": None if np.isnan(prior_fg3a36) else round(prior_fg3a36, 1),
            "fg3a_share": round(fg3a / fga, 3) if fga else None,
        })
    df = pd.DataFrame(rows)
    df["d_usg"] = (df.usg - df.usg_prior).round(1)
    df["gap"] = (df.usg - df.usg_model).round(1)            # what the shrinkage still holds back
    df["d_mpg"] = (df.mpg - df.mpg_prior).round(1)
    df["d_fg3a36"] = (df.fg3a36 - df.fg3a36_prior).round(1)
    enough = df.minutes >= config.SHIFT_MIN_MINUTES
    f = config.SHIFT_FLAGS
    flags = []
    for r in df.itertuples():
        out = []
        if r.minutes >= config.SHIFT_MIN_MINUTES and r.has_prior:
            if abs(r.d_usg) >= f["usage"]:
                out.append(f"usage {r.d_usg:+.1f}")
            if abs(r.d_mpg) >= f["minutes"]:
                out.append(f"minutes {r.d_mpg:+.1f}")
            if pd.notna(r.d_fg3a36) and abs(r.d_fg3a36) >= f["fg3a36"]:
                out.append(f"3PA/36 {r.d_fg3a36:+.1f}")
        flags.append(", ".join(out))
    df["flags"] = flags
    df["flagged"] = enough & df["flags"].ne("")
    df["score"] = (df.d_usg.abs() / f["usage"] + df.d_mpg.abs() / f["minutes"]
                   + df.d_fg3a36.abs().fillna(0) / f["fg3a36"]) * np.sqrt(df.minutes / 100)
    return df.sort_values(["flagged", "score"], ascending=False).reset_index(drop=True)
