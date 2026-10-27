"""Box scores from SportsGameOdds results: one row per player-game and one per team-game.

results.game.<playerID> carries a player's full-game line (secondsPlayed, fieldGoalsAttempted,
turnovers, ...) and results.game.home / .away the team totals. SportsGameOdds lists only the
players it carries for the event (the ones with props, about 21 a game), so the deep bench is
missing: team totals come from the team rows, never from summing players, and team minutes
from the periods played (240, plus 25 per overtime). A listed player with no line did not play.

Usage rate (the standard box-score formula):

    USG% = 100 * ((FGA + 0.44 FTA + TOV) * (team minutes / 5))
                 / (minutes * (team FGA + 0.44 team FTA + team TOV))

Possessions = FGA + 0.44 FTA - OREB + TOV (team), and pace = possessions per 48 minutes.
Rows are append-only and a game is stored once: re-ingesting it adds nothing.
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import config
from .config import team_abbr
from .schedule import et_date
from .storage import Storage, to_naive_utc

# box-score column -> SportsGameOdds results key
STAT_KEYS = {"pts": "points", "reb": "rebounds", "oreb": "offensiveRebounds", "dreb": "defensiveRebounds",
             "ast": "assists", "stl": "steals", "blk": "blocks", "tov": "turnovers",
             "fgm": "fieldGoalsMade", "fga": "fieldGoalsAttempted", "fg3m": "threePointersMade",
             "fg3a": "threePointersAttempted", "ftm": "freeThrowsMade", "fta": "freeThrowsAttempted",
             "pf": "fouls", "plus_minus": "plusMinus"}
REGULATION_MIN = 240.0           # 5 players x 48 minutes
OVERTIME_MIN = 25.0              # 5 players x 5 minutes
FTA_WEIGHT = 0.44


def usage_pct(fga, fta, tov, minutes, team_fga, team_fta, team_tov, team_minutes):
    """USG% from the formula in the module docstring. Scalars or aligned Series; NaN where the
    player has no minutes or the team made no plays."""
    num = (np.asarray(fga, float) + FTA_WEIGHT * np.asarray(fta, float) + np.asarray(tov, float)) \
        * (np.asarray(team_minutes, float) / 5)
    den = np.asarray(minutes, float) * (np.asarray(team_fga, float) + FTA_WEIGHT * np.asarray(team_fta, float)
                                        + np.asarray(team_tov, float))
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(den > 0, 100 * num / np.where(den > 0, den, 1), np.nan)
    if isinstance(fga, pd.Series):
        return pd.Series(out, index=fga.index)
    return float(out) if np.ndim(out) == 0 else out


def possessions(fga, fta, oreb, tov):
    return fga + FTA_WEIGHT * fta - oreb + tov


def overtimes(event: dict) -> int:
    """Overtime periods played: results keys like `ot` / `2ot`, and never fewer than both teams'
    listed minutes imply (a team's players can't play more than its minutes; both teams, since
    one player tagged with the wrong team can push one side past 240)."""
    results = event.get("results") or {}
    n = sum(1 for k in results if "ot" in str(k).lower())
    game = results.get("game") or {}
    teams = {side: (event.get("teams") or {}).get(side, {}).get("teamID") for side in ("home", "away")}
    players = event.get("players") or {}
    implied = []
    for team_id in teams.values():
        secs = sum(float(s.get("secondsPlayed") or 0) for pid, s in game.items()
                   if pid not in ("home", "away") and isinstance(s, dict)
                   and (players.get(pid) or {}).get("teamID") == team_id)
        implied.append(math.ceil(max(0.0, secs / 60 - REGULATION_MIN - 0.5) / OVERTIME_MIN))
    return max(n, min(implied))


def _num(stats: dict, key: str) -> float | None:
    v = stats.get(key)
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def box_score_rows(event: dict, ts: datetime, source: str) -> tuple[list[dict], list[dict]]:
    """(player rows, team rows) for a finalized event; ([], []) for anything else."""
    status = event.get("status") or {}
    game = (event.get("results") or {}).get("game") or {}
    if not status.get("finalized") or not isinstance(game.get("home"), dict) or not isinstance(game.get("away"), dict):
        return [], []
    eid, starts = event["eventID"], to_naive_utc(status.get("startsAt"))
    team_ids = {side: ((event.get("teams") or {}).get(side) or {}).get("teamID") for side in ("home", "away")}
    abbr = {side: team_abbr(t) for side, t in team_ids.items()}
    side_of = {t: side for side, t in team_ids.items()}
    n_ot = overtimes(event)
    team_minutes = REGULATION_MIN + OVERTIME_MIN * n_ot
    players = event.get("players") or {}

    teams = {}
    for side in ("home", "away"):
        t = game[side]
        row = {"ts": ts, "event_id": eid, "starts_at": starts, "team": abbr[side],
               "opponent": abbr["away" if side == "home" else "home"], "home": side == "home",
               "overtimes": n_ot, "team_minutes": team_minutes, "source": source}
        row.update({col: _num(t, key) for col, key in STAT_KEYS.items()})
        row["possessions"] = (possessions(row["fga"], row["fta"], row["oreb"], row["tov"])
                              if None not in (row["fga"], row["fta"], row["oreb"], row["tov"]) else None)
        teams[side] = row

    rows = []
    for pid, p in players.items():
        side = side_of.get(p.get("teamID"))
        if side is None:
            continue
        stats = game.get(pid)
        line = isinstance(stats, dict)
        seconds = _num(stats, "secondsPlayed") if line else None
        played = line and (seconds is None or seconds > 0)
        row = {"ts": ts, "event_id": eid, "starts_at": starts, "team": abbr[side],
               "opponent": abbr["away" if side == "home" else "home"], "home": side == "home",
               "player_id": p.get("playerID", pid),
               "player_name": p.get("name") or " ".join(x for x in (p.get("firstName"), p.get("lastName")) if x),
               "played": bool(played), "seconds": seconds,
               "minutes": None if seconds is None else seconds / 60, "source": source}
        row.update({col: (_num(stats, key) if line else None) for col, key in STAT_KEYS.items()})
        t = teams[side]
        ok = played and row["minutes"] and None not in (row["fga"], row["fta"], row["tov"], t["fga"], t["fta"], t["tov"])
        row["usg_pct"] = (usage_pct(row["fga"], row["fta"], row["tov"], row["minutes"],
                                    t["fga"], t["fta"], t["tov"], team_minutes) if ok else None)
        rows.append(row)
    listed = {}
    for r in rows:
        listed[r["team"]] = listed.get(r["team"], 0.0) + (r["minutes"] or 0.0)
    for t in teams.values():
        t["listed_minutes"] = listed.get(t["team"], 0.0)
    return rows, list(teams.values())


def stored_box_events(storage: Storage) -> set[str]:
    return set(storage.query("SELECT DISTINCT event_id FROM team_box_scores").event_id)


def store_box_scores(storage: Storage, events: list[dict], now: datetime, source: str = "api") -> dict:
    """Append box scores for finalized events not stored yet. Returns counts."""
    have = stored_box_events(storage)
    counts = {"games": 0, "players": 0, "skipped": 0}
    for ev in events:
        if ev.get("eventID") in have:
            counts["skipped"] += 1
            continue
        players, teams = box_score_rows(ev, now, source)
        if not teams:
            continue
        counts["players"] += storage.append("box_scores", players)
        storage.append("team_box_scores", teams)
        counts["games"] += 1
        have.add(ev["eventID"])
    return counts


def results_files(raw_dir: Path | None = None) -> list[Path]:
    return sorted((raw_dir or config.RAW_DIR).glob("*/*results*.json"))


def backfill_from_raw(storage: Storage, now: datetime, raw_dir: Path | None = None) -> dict:
    """Box scores from every saved results response (no API call)."""
    total = {"files": 0, "games": 0, "players": 0, "skipped": 0}
    for path in results_files(raw_dir):
        payload = json.loads(path.read_text())
        events = payload.get("data", payload) if isinstance(payload, dict) else payload
        c = store_box_scores(storage, events, now, source=f"raw:{path.parent.name}/{path.name}")
        total["files"] += 1
        for k in ("games", "players", "skipped"):
            total[k] += c[k]
    return total


def coverage(storage: Storage) -> pd.DataFrame:
    """Games, player lines and the share of team minutes the listed players cover, per ET date."""
    teams = storage.query("SELECT starts_at, team_minutes, listed_minutes FROM team_box_scores")
    if teams.empty:
        return pd.DataFrame()
    lines = storage.query("SELECT starts_at FROM box_scores WHERE played")
    teams["et_date"] = teams.starts_at.map(et_date)
    out = teams.groupby("et_date").agg(games=("team_minutes", "size"), team_minutes=("team_minutes", "sum"),
                                       listed=("listed_minutes", "sum"))
    out["games"] //= 2
    out["lines"] = lines.starts_at.map(et_date).value_counts().reindex(out.index).fillna(0).astype(int)
    out["listed_share"] = (out.listed / out.team_minutes).round(3)
    return out[["games", "lines", "listed_share"]].reset_index()
