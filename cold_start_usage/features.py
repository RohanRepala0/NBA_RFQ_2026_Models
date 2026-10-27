"""As-of opportunity features: what a player's recent games say about his minutes and role.

Everything here takes `before` (a game's tip) and reads only box scores of games on earlier
ET dates, so a game's own line, or a later one, can never reach its projection.

Per player (box scores of games he played, newest first):
- minutes, FGA, FTA, TOV and usage over the last 5 and 20 games, and momentum = 5 - 20;
- per-minute rates over the last 20 games for points, rebounds, assists, threes, steals,
  blocks and turnovers, shrunk toward last season (empirical Bayes in minutes):

      rate = (K * prior_rate + sum(stat)) / (K + sum(minutes)),  K = k_games * prior_mpg

  with k_games per stat in config.ROLLING_PRIOR_GAMES (halved for a player on a new team).
  No prior row (a rookie): the as-of league rate for his minutes tier;
- role stability from the last 10 games: the coefficient of variation of minutes, usage and
  points per minute, as a class (config.ROLE_CLASSES), which widens the points SD.

Per game: each team's pace (possessions per 48) and what its opponents scored, rebounded and
so on per possession against it, shrunk toward the league with config.TEAM_PRIOR_GAMES, as
multipliers clamped to config.CONTEXT_CLAMP.

Minutes: each available player's recent minutes (last 5) shrunk toward the chosen scenario's,
then the team is brought to 240: a shortfall goes to players by headroom under
config.ROLLING_MINUTES_CAP (rotation players absorb more than a starter already near the
cap), an excess comes off in proportion to minutes.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import config
from .boxscores import REGULATION_MIN
from .players import load_overrides, name_key
from .schedule import et_date, et_day_bounds
from .storage import Storage

# feature stat -> box-score column
RATE_STATS = {"points": "pts", "rebounds": "reb", "assists": "ast", "threes": "fg3m",
              "steals": "stl", "blocks": "blk", "turnovers": "tov"}
WINDOW_SHORT, WINDOW_LONG, WINDOW_ROLE = 5, 20, 10
MINUTES_TIERS = (15.0, 25.0)            # prior minutes tiers for players with no prior row
ROLE_MIN_MINUTES = 6.0                  # games shorter than this stay out of the usage and scoring CVs


def history(storage: Storage, before) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(player lines played, team rows) of games on ET dates before `before`'s: a game earlier
    the same evening isn't final at a later tip (and its box score arrives with the next
    morning's grade anyway)."""
    cutoff, _ = et_day_bounds(et_date(before))
    box = storage.query("SELECT * FROM box_scores WHERE played AND starts_at < ? ORDER BY starts_at DESC",
                        [cutoff])
    teams = storage.query("SELECT * FROM team_box_scores WHERE starts_at < ?", [cutoff])
    return box, teams


# --- priors -----------------------------------------------------------------------------
def prior_rates(players: pd.DataFrame) -> pd.DataFrame:
    """Last season's per-minute rates and usage per player row (players_2025_26.csv)."""
    p = players.copy()
    mpg = p.mpg.where(p.mpg > 0)
    out = pd.DataFrame({"player": p.player, "sgo_player_id": p.get("sgo_player_id"),
                        "team_2025_26": p.team_2025_26, "team_2026_27": p.team_2026_27,
                        "prior_mpg": p.mpg, "prior_usg": p.usg_pct})
    out["prior_points"] = p.ppg / mpg
    out["prior_rebounds"] = p.rpg / mpg if "rpg" in p else np.nan
    out["prior_assists"] = p.apg / mpg if "apg" in p else np.nan
    if {"fg3a_pg", "fg3_pct"} <= set(p.columns):      # no attempts means no 3P% in the table: a 0 rate, not unknown
        out["prior_threes"] = (p.fg3a_pg * p.fg3_pct.where(p.fg3a_pg > 0, 0.0) / 100) / mpg
    else:
        out["prior_threes"] = np.nan
    for s in ("steals", "blocks", "turnovers"):
        out[f"prior_{s}"] = np.nan              # not in last season's table: the league rate stands in
    out.loc[p.verified.ne("yes"), [f"prior_{s}" for s in RATE_STATS]] = np.nan
    return out


def league_rates(box: pd.DataFrame, priors: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Per-minute league rates by minutes tier ('low' < 15 < 'mid' < 25 < 'high'): from this
    season's box scores before tip where they exist, else from last season's table."""
    out = {}
    for tier, lo, hi in (("low", 0, MINUTES_TIERS[0]), ("mid", *MINUTES_TIERS), ("high", MINUTES_TIERS[1], 99)):
        rates = {}
        pr = priors[(priors.prior_mpg >= lo) & (priors.prior_mpg < hi)]
        b = box[box.minutes.notna()] if len(box) else box
        if len(b):
            avg = b.groupby("player_id").minutes.transform("mean")
            b = b[(avg >= lo) & (avg < hi)]
        for stat, col in RATE_STATS.items():
            mins = float(b.minutes.sum()) if len(b) else 0.0
            if mins >= 300:
                rates[stat] = float(b[col].sum()) / mins
            else:
                rates[stat] = float((pr[f"prior_{stat}"] * pr.prior_mpg).sum() / pr.prior_mpg[pr[f"prior_{stat}"].notna()].sum()) \
                    if pr[f"prior_{stat}"].notna().any() else float("nan")
        rates["usage"] = float(np.average(pr.prior_usg.dropna(), weights=pr.prior_mpg[pr.prior_usg.notna()])) \
            if pr.prior_usg.notna().any() else 20.0
        out[tier] = rates
    return out


def _tier(mpg: float) -> str:
    return "low" if mpg < MINUTES_TIERS[0] else "mid" if mpg < MINUTES_TIERS[1] else "high"


# --- player features ----------------------------------------------------------------------
def _cv(x: pd.Series) -> float:
    x = x.dropna()
    return float(x.std(ddof=0) / x.mean()) if len(x) >= 2 and x.mean() > 0 else float("nan")


def role_class(n: int, m10: float, cv_min: float, cv_usg: float, cv_pts: float) -> str:
    c = config.ROLE_CLASSES
    if n < c["min_games"] or any(math.isnan(v) for v in (cv_min, cv_usg, cv_pts)):
        return "unknown"
    if m10 >= c["engine_minutes"] and cv_min <= c["engine_cv_minutes"] and cv_usg <= c["engine_cv_usage"]:
        return "engine"
    if cv_pts >= c["heat_check_cv_points"]:
        return "heat_check"
    if cv_min >= c["volatile_cv_minutes"]:
        return "volatile_role"
    return "steady"


def shrink(prior: float, k_minutes: float, total: float, minutes: float) -> float:
    """(K * prior + total) / (K + minutes): the prior alone at 0 minutes, the sample in the limit."""
    if k_minutes + minutes <= 0:
        return float("nan")
    return (k_minutes * prior + total) / (k_minutes + minutes)


@dataclass(frozen=True)
class Prior:
    mpg: float
    usg: float
    rates: dict
    new_team: bool
    has_row: bool


def player_prior(row: pd.Series | None, league: dict, team: str, scen_minutes: float) -> Prior:
    if row is None:
        tier = league[_tier(scen_minutes)]
        return Prior(mpg=scen_minutes, usg=tier["usage"], rates={s: tier[s] for s in RATE_STATS},
                     new_team=True, has_row=False)
    mpg = float(row.prior_mpg) if pd.notna(row.prior_mpg) and row.prior_mpg > 0 else scen_minutes
    tier = league[_tier(mpg)]
    rates = {s: (float(row[f"prior_{s}"]) if pd.notna(row[f"prior_{s}"]) else tier[s]) for s in RATE_STATS}
    usg = float(row.prior_usg) if pd.notna(row.prior_usg) else tier["usage"]
    new_team = pd.notna(row.team_2025_26) and row.team_2025_26 != team
    return Prior(mpg=mpg, usg=usg, rates=rates, new_team=bool(new_team), has_row=True)


def player_features(games: pd.DataFrame, prior: Prior) -> dict:
    """One player's features from his played games (newest first) and his prior."""
    g = games[games.minutes.notna() & (games.minutes > 0)]
    last5, last20, last10 = g.head(WINDOW_SHORT), g.head(WINDOW_LONG), g.head(WINDOW_ROLE)
    n = len(last20)
    scale = config.TEAM_CHANGE_PRIOR_SCALE if prior.new_team else 1.0
    k = {s: config.ROLLING_PRIOR_GAMES[s] * scale * max(prior.mpg, 1.0) for s in (*RATE_STATS, "usage")}
    mins20 = float(last20.minutes.sum())
    out = {"games": n,
           "min_5": last5.minutes.mean() if len(last5) else np.nan,
           "min_20": last20.minutes.mean() if n else np.nan}
    for col in ("fga", "fta", "tov"):
        out[f"{col}_5"] = last5[col].mean() if len(last5) else np.nan
        out[f"{col}_20"] = last20[col].mean() if n else np.nan
    for w, part in (("5", last5), ("20", last20)):
        u = part[part.usg_pct.notna()]
        out[f"usg_{w}"] = float(np.average(u.usg_pct, weights=u.minutes)) if len(u) else np.nan
    out["d_min"] = out["min_5"] - out["min_20"]
    out["d_usg"] = out["usg_5"] - out["usg_20"]
    u20 = last20[last20.usg_pct.notna()]
    out["usg"] = shrink(prior.usg, k["usage"], float((u20.usg_pct * u20.minutes).sum()), float(u20.minutes.sum()))
    for stat, col in RATE_STATS.items():
        out[f"rate_{stat}"] = shrink(prior.rates[stat], k[stat], float(last20[col].sum()), mins20)
        out[f"raw_rate_{stat}"] = float(last20[col].sum()) / mins20 if mins20 > 0 else np.nan
    p5 = float(last5.pts.sum()) / float(last5.minutes.sum()) if len(last5) else np.nan
    out["d_pts_rate"] = p5 - out["raw_rate_points"] if n else np.nan
    real = last10[last10.minutes >= ROLE_MIN_MINUTES]             # a 1-minute cameo isn't a usage sample
    out["cv_min"] = _cv(last10.minutes)
    out["cv_usg"], out["cv_pts"] = _cv(real.usg_pct), _cv(real.pts / real.minutes)
    out["role"] = role_class(len(last10), float(last10.minutes.mean()) if len(last10) else 0.0,
                             out["cv_min"], out["cv_usg"], out["cv_pts"])
    out["prior_mpg"], out["prior_usg"], out["new_team"], out["has_prior"] = (prior.mpg, prior.usg,
                                                                           prior.new_team, prior.has_row)
    return out


# --- minutes ------------------------------------------------------------------------------
def rolling_minutes(scen: pd.DataFrame, recent: dict[str, tuple[float, int]],
                    total: float = REGULATION_MIN) -> pd.DataFrame:
    """scen: player, proj_mpg (the chosen scenario: who is available and the reviewed minutes).
    recent: player -> (mean minutes over his last 5 games, games). Returns player, proj_mpg,
    scen_mpg, recent_mpg summing to `total`."""
    k = config.ROLLING_PRIOR_GAMES["minutes"]
    cap = config.ROLLING_MINUTES_CAP
    df = scen[scen.proj_mpg > 0][["player", "proj_mpg"]].rename(columns={"proj_mpg": "scen_mpg"}).copy()
    df["recent_mpg"] = df.player.map(lambda p: recent.get(p, (np.nan, 0))[0])
    df["recent_n"] = df.player.map(lambda p: recent.get(p, (np.nan, 0))[1]).astype(float)
    w = df.recent_n.clip(upper=WINDOW_SHORT)
    df["base"] = np.where(w > 0, (k * df.scen_mpg + w * df.recent_mpg.fillna(0)) / (k + w), df.scen_mpg)
    gap = total - float(df.base.sum())
    if gap > 0:
        room = (df.base * (cap - df.base).clip(lower=0))
        if room.sum() <= 0:
            room = pd.Series(1.0, index=df.index)
        add = gap * room / room.sum()
        # Never push anyone past the cap while others have room (a few passes settle it).
        for _ in range(10):
            over = (df.base + add - np.maximum(cap, df.base)).clip(lower=0)
            if over.sum() < 1e-9:
                break
            add -= over
            free = room.where((df.base + add) < cap - 1e-9, 0)
            if free.sum() <= 0:
                break
            add += over.sum() * free / free.sum()
        df["proj_mpg"] = df.base + add
    else:
        df["proj_mpg"] = df.base * total / float(df.base.sum())
    df["proj_mpg"] = df.proj_mpg * total / float(df.proj_mpg.sum())
    return df[["player", "proj_mpg", "scen_mpg", "recent_mpg", "recent_n"]].reset_index(drop=True)


# --- team context -------------------------------------------------------------------------
def _pace(rows: pd.DataFrame) -> pd.Series:
    return 48 * rows.possessions / (rows.team_minutes / 5)


def team_context(teams: pd.DataFrame, team: str, opponent: str) -> dict:
    """Multipliers for `team`'s players against `opponent`: pace and, per stat, what the
    opponent allows per possession, both shrunk to the league and clamped."""
    lo, hi = config.CONTEXT_CLAMP
    out = {"pace_mult": 1.0, **{f"def_{s}": 1.0 for s in RATE_STATS}, "team_games": 0, "opp_games": 0}
    t = teams[teams.possessions.notna() & (teams.possessions > 0)] if len(teams) else teams
    if t.empty:
        return out
    league_pace = float(_pace(t).mean())
    k = config.TEAM_PRIOR_GAMES

    def pace_hat(code):
        rows = t[t.team == code]
        return (k * league_pace + float(_pace(rows).sum())) / (k + len(rows)), len(rows)

    own, n_own = pace_hat(team)
    opp, n_opp = pace_hat(opponent)
    out["pace_mult"] = float(np.clip(((own + opp) / 2) / own, lo, hi))
    out["team_games"], out["opp_games"] = n_own, n_opp
    allowed = t[t.opponent == opponent]                  # what opponent's opponents did against it
    for stat, col in RATE_STATS.items():
        league = float(t[col].sum() / t.possessions.sum())
        if not league > 0:
            continue
        got = float(allowed[col].sum()); poss = float(allowed.possessions.sum())
        k_poss = k * float(t.possessions.mean())
        rate = (k_poss * league + got) / (k_poss + poss)
        out[f"def_{stat}"] = float(np.clip(rate / league, lo, hi))
    return out


# --- one team's inputs for the usage model ------------------------------------------------
def player_ids(names: list[str], team: str, mapping: dict[str, str], priors: pd.DataFrame,
               box: pd.DataFrame) -> dict[str, str | None]:
    """name -> SportsGameOdds player id: the event's mapping, then data/player_id_overrides.csv
    and last season's table, then a name match among this team's box scores."""
    explicit = {**(dict(zip(priors.player, priors.sgo_player_id)) if "sgo_player_id" in priors else {}),
                **load_overrides()}
    seen = {}
    if len(box):
        mine = box[box.team == team].drop_duplicates("player_id")
        seen = {name_key(n): pid for n, pid in zip(mine.player_name, mine.player_id)}
    out = {}
    for n in names:
        pid = mapping.get(n) or explicit.get(n)
        out[n] = pid if isinstance(pid, str) and pid else seen.get(name_key(n))
    return out


def recent_rotation(box: pd.DataFrame, team: str, exclude: set[str], n_games: int = WINDOW_SHORT) -> pd.DataFrame:
    """Players who played for `team` in its last n games and aren't in `exclude` (player ids):
    player (the box-score name), player_id and proj_mpg = his minutes per team game over those
    games (a game he missed counts as 0)."""
    mine = box[(box.team == team) & box.minutes.notna()] if len(box) else box
    if mine.empty:
        return pd.DataFrame(columns=["player", "proj_mpg", "player_id"])
    games = mine.drop_duplicates("event_id").sort_values("starts_at", ascending=False).event_id.head(n_games)
    part = mine[mine.event_id.isin(set(games)) & ~mine.player_id.isin(exclude)]
    out = part.groupby("player_id").agg(player=("player_name", "first"), total=("minutes", "sum")).reset_index()
    out["proj_mpg"] = out.total / len(games)
    return out[out.proj_mpg > 0][["player", "proj_mpg", "player_id"]]


def rolling_inputs(players: pd.DataFrame, scen: pd.DataFrame, team: str, opponent: str,
                   box: pd.DataFrame, teams: pd.DataFrame, mapping: dict[str, str] | None = None,
                   out_names: tuple[str, ...] = (), out_ids: tuple[str, ...] = ()):
    """(players-like table, scenario, features, context) for usage_model.project_scenario.

    Who plays: the chosen scenario's players plus anyone else who played for the team in its
    last 5 games (the deep bench the scenario leaves out takes about 50 minutes a game), less
    the players ruled out (`out_names`: in full strength but not in the chosen scenario;
    `out_ids`: listed out for the event).

    The players-like table carries each player's shrunk usage as usg_pct and his shrunk rates
    times his new minutes as ppg / rpg / apg with mpg = those minutes, so project_scenario's
    usage budget and rebound / assist budgets run unchanged on the rolling inputs."""
    priors = prior_rates(players)
    league = league_rates(box, priors)
    by_name = priors.set_index("player")
    shooting = players.set_index("player")
    scen = scen[scen.proj_mpg > 0][["player", "proj_mpg"]]
    ids = player_ids(scen.player.tolist(), team, mapping or {}, priors, box)
    gone = {i for i in player_ids(list(out_names), team, {}, priors, box).values() if i} | set(out_ids)
    bench = recent_rotation(box, team, {i for i in ids.values() if i} | gone)
    bench = bench[~bench.player.isin(set(scen.player))]
    # SportsGameOdds sometimes tags a player with the other team in one game: a bench candidate
    # last season's table puts on another 2026-27 team isn't this team's.
    elsewhere = set(priors.sgo_player_id[priors.team_2026_27.ne(team)].dropna())
    bench = bench[~bench.player_id.isin(elsewhere)]
    ids.update(dict(zip(bench.player, bench.player_id)))
    scen = pd.concat([scen, bench[["player", "proj_mpg"]]], ignore_index=True)
    feats, recent = {}, {}
    for r in scen.itertuples():
        pid = ids.get(r.player)
        games = box[box.player_id == pid] if pid else box.iloc[0:0]
        row = by_name.loc[r.player] if r.player in by_name.index else None
        f = player_features(games, player_prior(row, league, team, float(r.proj_mpg)))
        f["player_id"] = pid if isinstance(pid, str) and pid else None
        feats[r.player] = f
        g = games[games.minutes.notna() & (games.minutes > 0)].head(WINDOW_SHORT)
        recent[r.player] = (float(g.minutes.mean()) if len(g) else np.nan, len(g))
    mins = rolling_minutes(scen, recent)
    ctx = team_context(teams, team, opponent)
    rows = []
    for m in mins.itertuples():
        f, mpg = feats[m.player], float(m.proj_mpg)
        known = m.player in shooting.index
        rows.append({"player": m.player, "team_2025_26": by_name.team_2025_26.get(m.player), "team_2026_27": team,
                     "usg_pct": f["usg"], "games": f["games"], "mpg": mpg,
                     "ppg": f["rate_points"] * mpg, "rpg": f["rate_rebounds"] * mpg, "apg": f["rate_assists"] * mpg,
                     # spacing scales 3PA by proj_mpg / mpg, and mpg here is the new minutes
                     "fg3a_pg": (shooting.at[m.player, "fg3a_pg"] / shooting.at[m.player, "mpg"] * mpg
                                 if known and "fg3a_pg" in shooting.columns and shooting.at[m.player, "mpg"] > 0
                                 else np.nan),
                     "fg3_pct": shooting.at[m.player, "fg3_pct"] if known and "fg3_pct" in shooting.columns else np.nan,
                     "verified": "yes", "source": "rolling"})
    feat_df = pd.DataFrame([{"player": n, **f} for n, f in feats.items()]).merge(mins, on="player", how="left")
    return pd.DataFrame(rows), mins[["player", "proj_mpg"]], feat_df, ctx


def project_rolling(players: pd.DataFrame, scen: pd.DataFrame, team: str, opponent: str,
                    box: pd.DataFrame, teams: pd.DataFrame, mapping: dict[str, str] | None = None,
                    team_shooting: pd.DataFrame | None = None, params=None,
                    out_names: tuple[str, ...] = (), out_ids: tuple[str, ...] = ()):
    """usage_model.project_scenario on the rolling inputs, times the pace and opponent
    multipliers, with the role class widening the points SD, plus the logged-only stats
    (config.EXTRA_STATS: threes and turnovers move with usage, steals and blocks don't).
    Returns (projection frame, players-like inputs, minutes, context)."""
    from . import distributions
    from .usage_model import MODEL, PROJECTION_COLUMNS, project_scenario
    params = params or MODEL
    like, mins, feats, ctx = rolling_inputs(players, scen, team, opponent, box, teams, mapping, out_names, out_ids)
    res = project_scenario(like, mins, params, team_shooting=team_shooting)
    feats = feats.drop(columns=[c for c in feats.columns if c in res.columns and c != "player"])
    res = res.merge(feats, on="player", how="left", validate="one_to_one")
    for stat, (mean_col, sd_col) in PROJECTION_COLUMNS.items():
        res[mean_col] = res[mean_col] * ctx["pace_mult"] * ctx[f"def_{stat}"]
        res[sd_col] = res[mean_col].map(lambda m, s=stat: distributions.sd(s, m, params) if pd.notna(m) else np.nan)
    res["sd_proj"] = res.sd_proj * res.role.map(config.ROLE_SD_MULT).fillna(1.0)
    res["fair_line"] = (res.ppg_proj * 2).round() / 2
    squeeze = res.usg_proj / res.usg_pct
    for stat in config.EXTRA_STATS:
        m = res[f"rate_{stat}"].astype(float) * res.proj_mpg * ctx["pace_mult"] * ctx[f"def_{stat}"]
        res[f"{stat}_proj"] = (m * squeeze if stat in ("threes", "turnovers") else m).astype(float)
        res[f"{stat}_sd"] = np.sqrt(res[f"{stat}_proj"].clip(lower=0))     # Poisson until fitted
    return res, like, mins, ctx


def rolling_inputs_hash(like: pd.DataFrame, mins: pd.DataFrame, ctx: dict) -> str:
    """inputs_hash of the rolling inputs, plus what else moves a rolling projection: the pace and
    opponent context and the rolling settings."""
    import hashlib
    import json

    from .usage_model import inputs_hash
    keys = ("ROLLING_MODEL_VERSION", "ROLLING_PRIOR_GAMES", "TEAM_CHANGE_PRIOR_SCALE", "ROLLING_MINUTES_CAP",
            "TEAM_PRIOR_GAMES", "CONTEXT_CLAMP", "ROLE_CLASSES", "ROLE_SD_MULT")
    payload = {"base": inputs_hash(like, mins), "context": {k: round(float(v), 6) for k, v in ctx.items()},
               "config": {k: getattr(config, k) for k in keys}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]
