"""Does an early-season shift last? Fits the rolling model's shrinkage on last season's games.

The rolling model shrinks a player's rates toward last season's with k games of prior
(features.py: rate = (K * prior + sum) / (K + minutes), K = k * prior_mpg). This study
replays that on 2025-26: for a sample of players, the prior is 2024-25 (season totals), the
"early" sample his first n games of 2025-26 (n = 1..15) and the target the rest of his
2025-26 season. The k that best predicts the rest of the season from the first n games is
the one the model should use; minutes use rolling_minutes' rule (the last 5 games against k
games of the prior mpg).

Inputs (no API calls here): text copied from Court AI (an approved source of box-score facts;
its prices are never read) into one directory per player and call:
- <slug>__season_2024-25.txt: get_season_stats(2024-25), for the prior totals and usage;
- <slug>__<FGA|FTA|TOV|3PM>.txt: query_game_logs(season 2025-26, market) game lines.
Court AI's game logs carry no per-game usage, so usage comes from the plays proxy
FGA + 0.44 FTA + TOV per minute, scaled to the player's official 2025-26 usage
(players_2025_26.csv): his early and late usage keep their true ratio and the official scale.
A file whose game lines don't reproduce its own printed averages is rejected.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from . import config
from .boxscores import FTA_WEIGHT

MARKETS = ("FGA", "FTA", "TOV", "3PM")
CUTS = range(1, 16)                 # early samples of 1..15 games
MIN_REST_GAMES = 20                 # a target needs the rest of a season, not a few games
MIN_PRIOR_GAMES = 25
K_GRID = (0.0, 0.5, 1, 1.5, 2, 3, 4, 5, 6, 7, 8, 10, 12, 15, 20, 25, 30, 40, 60, 100)
SCALE_GRID = (0.25, 0.5, 0.75, 1.0, 1.5)
SHIFT_USG = 3.0                     # a usage shift worth asking about (points of USG%)
# study stat -> (game-log column, season-totals key); usage and minutes are handled apart
RATE_COLS = {"points": ("PTS", "PTS"), "rebounds": ("REB", "REB"), "assists": ("AST", "AST"),
             "threes": ("3PM", "3PM"), "turnovers": ("TOV", "TOV")}

GAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}) (vs|@) ([A-Z]{2,4}): (.+)$")
PAIR_RE = re.compile(r"([A-Z0-9%_]+) (-?\d+(?:\.\d+)?|—|-|n/a|null)")


def slug(name: str) -> str:
    import unicodedata
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", plain.lower()).strip("_")


def _pairs(text: str) -> dict[str, float]:
    out = {}
    for k, v in PAIR_RE.findall(text):
        try:
            out[k] = float(v)
        except ValueError:
            out[k] = np.nan
    return out


def parse_season(text: str) -> dict:
    """get_season_stats text -> team, gp, usg and the season totals (PTS, MIN, FGA, ...)."""
    out = {"team": None, "gp": np.nan, "usg": np.nan}
    if m := re.search(r"team ([A-Z]{2,4})\b", text):
        out["team"] = m.group(1)
    if m := re.search(r"\bGP (\d+)", text):
        out["gp"] = float(m.group(1))
    if m := re.search(r"\bUSG ([\d.]+)%", text):
        out["usg"] = float(m.group(1))
    if m := re.search(r"^Totals: (.+)$", text, re.M):
        out.update({f"tot_{k}": v for k, v in _pairs(m.group(1)).items()})
    return out


def parse_logs(text: str, market: str) -> pd.DataFrame:
    """query_game_logs text -> one row per game (date, opp, home, MIN, <market>, PTS, REB, AST).
    Raises ValueError when the lines don't match the printed sample size or averages."""
    rows = []
    for line in text.splitlines():
        m = GAME_RE.match(line.strip())
        if m:
            rows.append({"date": m.group(1), "home": m.group(2) == "vs", "opp": m.group(3), **_pairs(m.group(4))})
    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError(f"{market}: no game lines")
    if market not in df:
        raise ValueError(f"{market}: game lines carry no {market}")
    if m := re.search(r"Sample: \d+ \S+ games for him, (\d+) matching", text):
        if int(m.group(1)) != len(df):
            raise ValueError(f"{market}: {len(df)} game lines, sample says {m.group(1)}")
    if m := re.search(r"^Season averages[^:]*:(.+)$", text, re.M):
        for k, v in _pairs(m.group(1)).items():
            if k in df and not np.isnan(v):
                got = float(df[k].fillna(0).mean())
                if abs(got - v) > (0.06 if k == "MIN" else 0.006):
                    raise ValueError(f"{market}: game lines average {k} {got:.3f}, printed {v}")
    if df.date.duplicated().any():
        raise ValueError(f"{market}: a date appears twice")
    return df


def load_player(raw_dir: Path, name: str) -> tuple[dict, pd.DataFrame] | None:
    """(prior, games oldest first) for one player, or None when a file is missing."""
    s = slug(name)
    season = raw_dir / f"{s}__season_2024-25.txt"
    if not season.exists() or not all((raw_dir / f"{s}__{m}.txt").exists() for m in MARKETS):
        return None
    prior = parse_season(season.read_text())
    games = None
    for m in MARKETS:
        df = parse_logs((raw_dir / f"{s}__{m}.txt").read_text(), m)
        keep = ["date", "home", "opp", "MIN", m, "PTS", "REB", "AST"] if games is None else ["date", m, "MIN"]
        part = df[keep].rename(columns={"MIN": "MIN_" + m}) if games is not None else df[keep]
        if games is None:
            games = part
        else:
            games = games.merge(part, on="date", how="outer", validate="1:1")
            if games["MIN_" + m].ne(games.MIN).any():
                raise ValueError(f"{name}: {m} game list differs from FGA's")
            games = games.drop(columns="MIN_" + m)
    return prior, games.sort_values("date").reset_index(drop=True)


def player_rows(name: str, prior: dict, games: pd.DataFrame, usg_2025_26: float, team_2025_26: str,
                target_end: str | None = None) -> list[dict]:
    """One row per early cut: the first n games' sums, the rest of the season's (through
    `target_end` when given, e.g. before the trade deadline) and the prior."""
    g = games[games.MIN > 0].copy()
    g["plays"] = g.FGA + FTA_WEIGHT * g.FTA + g.TOV
    if len(g) < MIN_REST_GAMES + 1 or g.plays.sum() <= 0 or not prior.get("tot_MIN"):
        return []
    scale = usg_2025_26 / (g.plays.sum() / g.MIN.sum())    # proxy -> official 2025-26 usage
    g["usg_x_min"] = scale * g.plays
    base = {"player": name, "team_2025_26": team_2025_26, "team_2024_25": prior.get("team"),
            "new_team": bool(prior.get("team") and team_2025_26 not in (prior.get("team"), "TOT")),
            "prior_gp": prior["gp"], "prior_mpg": prior["tot_MIN"] / prior["gp"], "prior_usg": prior["usg"],
            **{f"prior_{s}": prior.get(f"tot_{key}", np.nan) / prior["tot_MIN"] for s, (_, key) in RATE_COLS.items()}}
    rows = []
    for n in CUTS:
        early, rest = g.iloc[:n], g.iloc[n:]
        if target_end:
            rest = rest[rest.date <= target_end]
        if len(rest) < MIN_REST_GAMES:
            break
        r = {**base, "n": n, "early_min": early.MIN.sum(), "rest_min": rest.MIN.sum(), "rest_games": len(rest),
             "early_last5_mpg": early.MIN.tail(5).mean(), "early_last5_n": min(n, 5),
             "rest_mpg": rest.MIN.mean(), "early_usg_x_min": early.usg_x_min.sum(), "rest_usg_x_min": rest.usg_x_min.sum()}
        for s, (col, _) in RATE_COLS.items():
            r[f"early_{s}"], r[f"rest_{s}"] = float(early[col].sum()), float(rest[col].sum())
        rows.append(r)
    return rows


def study(raw_dir: Path, players: pd.DataFrame, target_end: str | None = None) -> tuple[pd.DataFrame, list[str]]:
    """Rows for every player with all files (players: players_2025_26.csv). Returns (rows, notes)."""
    rows, notes = [], []
    by_slug = {slug(p): r for p, r in zip(players.player, players.itertuples())}
    names = sorted({f.name.split("__")[0] for f in raw_dir.glob("*__season_2024-25.txt")})
    for s in names:
        row = by_slug.get(s)
        if row is None:
            notes.append(f"{s}: not in players_2025_26.csv")
            continue
        try:
            loaded = load_player(raw_dir, row.player)
        except ValueError as e:
            notes.append(f"{row.player}: rejected ({e})")
            continue
        if loaded is None:
            notes.append(f"{row.player}: files missing")
            continue
        prior, games = loaded
        if not prior["gp"] >= MIN_PRIOR_GAMES or np.isnan(prior["usg"]):
            notes.append(f"{row.player}: 2024-25 sample too small (GP {prior['gp']})")
            continue
        r = player_rows(row.player, prior, games, float(row.usg_pct), row.team_2025_26, target_end)
        if not r:
            notes.append(f"{row.player}: too few 2025-26 games ({len(games)})")
        rows += r
    return pd.DataFrame(rows), notes


# --- fitting ------------------------------------------------------------------------------
def estimate(df: pd.DataFrame, stat: str, k: float, team_scale: float = 1.0) -> tuple[pd.Series, pd.Series]:
    """(rolling estimate with k games of prior, rest-of-season target) per row, on the model's
    scale: usage in USG points, minutes per game, rates per 36 minutes."""
    k = k * np.where(df.new_team, team_scale, 1.0)
    if stat == "minutes":
        w = df.early_last5_n
        return (k * df.prior_mpg + w * df.early_last5_mpg) / (k + w), df.rest_mpg
    K = k * df.prior_mpg
    if stat == "usage":
        return (K * df.prior_usg + df.early_usg_x_min) / (K + df.early_min), df.rest_usg_x_min / df.rest_min
    est = (K * df[f"prior_{stat}"] + df[f"early_{stat}"]) / (K + df.early_min)
    return 36 * est, 36 * df[f"rest_{stat}"] / df.rest_min


def loss(df: pd.DataFrame, stat: str, k: float, team_scale: float = 1.0) -> float:
    est, target = estimate(df, stat, k, team_scale)
    ok = est.notna() & target.notna()
    return float(((est - target)[ok] ** 2).mean()) if ok.any() else float("nan")


def live_scale(stat: str) -> float:
    """The k multiplier the live model gives a player on a new team (rolling minutes use none)."""
    return 1.0 if stat == "minutes" else config.TEAM_CHANGE_PRIOR_SCALE


def best_k(df: pd.DataFrame, stat: str, grid=K_GRID, scale: float = 1.0) -> float:
    losses = [loss(df, stat, k, scale) for k in grid]
    return float(grid[int(np.nanargmin(losses))])


def bootstrap_k(df: pd.DataFrame, stat: str, reps: int = 200, seed: int = 0, scale: float = 1.0) -> tuple[float, float]:
    """10th-90th percentile of the best k over player-level resamples."""
    rng = np.random.default_rng(seed)
    players = df.player.unique()
    groups = {p: g for p, g in df.groupby("player")}
    ks = [best_k(pd.concat([groups[p] for p in rng.choice(players, len(players))]), stat, scale=scale)
          for _ in range(reps)]
    return float(np.percentile(ks, 10)), float(np.percentile(ks, 90))


STUDY_STATS = ("usage", "minutes", "points", "rebounds", "assists", "threes", "turnovers")


def fit(df: pd.DataFrame, reps: int = 200) -> pd.DataFrame:
    """Per stat: the current k, the fitted k (with a bootstrap band) and RMSE of the rest-of-season
    estimate at each, plus prior-only and sample-only."""
    out = []
    for stat in STUDY_STATS:
        k_now, scale = float(config.ROLLING_PRIOR_GAMES[stat]), live_scale(stat)
        k_fit = best_k(df, stat, scale=scale)
        lo, hi = bootstrap_k(df, stat, reps, scale=scale)
        out.append({"stat": stat, "k_now": k_now, "k_fit": k_fit, "k_p10": lo, "k_p90": hi,
                    "rmse_now": loss(df, stat, k_now, scale) ** 0.5, "rmse_fit": loss(df, stat, k_fit, scale) ** 0.5,
                    "rmse_prior_only": loss(df, stat, 1e9) ** 0.5, "rmse_sample_only": loss(df, stat, 0.0) ** 0.5})
    return pd.DataFrame(out)


def fit_by_cut(df: pd.DataFrame, stat: str, cuts=(3, 5, 10, 15)) -> pd.DataFrame:
    """The best k when only the first n games are known: one fixed k should fit them all."""
    rows = []
    for n in cuts:
        part = df[df.n == n]
        if len(part):
            rows.append({"stat": stat, "n": n, "players": len(part), "k_fit": best_k(part, stat, scale=live_scale(stat))})
    return pd.DataFrame(rows)


def team_scale(df: pd.DataFrame, stat: str = "usage") -> pd.DataFrame:
    """Players on a new team: RMSE by the k multiplier (the model uses TEAM_CHANGE_PRIOR_SCALE)."""
    moved = df[df.new_team]
    k = best_k(df[~df.new_team], stat)          # k from the players who stayed, the multiplier from those who moved
    return pd.DataFrame([{"stat": stat, "scale": s, "players": moved.player.nunique(),
                          "rmse": loss(moved, stat, k, s) ** 0.5 if len(moved) else np.nan} for s in SCALE_GRID])


def direction(df: pd.DataFrame, n: int = 5, threshold: float = SHIFT_USG) -> dict:
    """Of the players whose usage after n games was `threshold`+ points off last season's, how
    many stayed on that side for the rest of the season, and how much of the gap remained."""
    part = df[df.n == n]
    early = part.early_usg_x_min / part.early_min - part.prior_usg
    rest = part.rest_usg_x_min / part.rest_min - part.prior_usg
    big = early.abs() >= threshold
    kept = (np.sign(early[big]) == np.sign(rest[big]))
    slope = float(np.polyfit(early, rest, 1)[0]) if len(part) > 2 else float("nan")
    return {"n": n, "players": int(len(part)), "shifted": int(big.sum()), "kept": int(kept.sum()),
            "kept_pct": float(100 * kept.mean()) if big.any() else float("nan"),
            "share_kept": float((rest[big] / early[big]).median()) if big.any() else float("nan"),
            "slope_all": slope}
