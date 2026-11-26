"""Unattended rotations for the daily job: each team's minutes rebuilt from its recent box scores.

Nobody reviews minutes when the job runs on a schedule, so every team on the slate gets a
scenario named `auto` in its scenarios/TEAM.csv, rewritten once a day (git keeps each day's):

- minutes per team game over the team's last AUTO_WINDOW games, a game a player missed counting 0;
- less anyone who didn't play in any of the team's last AUTO_GONE_AFTER games (hurt, traded,
  out of the rotation): one who comes back re-enters through the rolling model's bench adds;
- less anyone under AUTO_MIN_MPG, then brought to 240 with nobody over AUTO_CAP.

Players listed out for the game come off later, in the rolling projection (its `out_ids` read
the event roster's statuses at each checkpoint), so a status change needs no new scenario. A
hand-built `report_MMDD` scenario for the day (a session that reviewed the report) wins over
`auto`, and a team with too few games stored keeps its latest committed scenario.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from . import config
from .players import load_overrides, name_key
from .usage_model import load_players, load_scenarios, scenario_path

AUTO = "auto"
AUTO_WINDOW = 10
AUTO_GONE_AFTER = 3
AUTO_MIN_GAMES = 3
AUTO_MIN_MPG = 6.0
AUTO_CAP = 37.0
TOTAL = 240.0


def to_total(minutes: pd.Series, total: float = TOTAL, cap: float = AUTO_CAP) -> pd.Series:
    """Minutes brought to `total`: a shortfall goes out in proportion to minutes among players
    under the cap (never past it), an excess comes off in proportion. Rounded to 0.1 with the
    remainder on the player with the most room."""
    m = minutes.astype(float).clip(upper=cap)
    for _ in range(50):
        gap = total - float(m.sum())
        if abs(gap) < 1e-6:
            break
        if gap < 0:
            m = m * total / float(m.sum())
            continue
        room = (cap - m).clip(lower=0)
        weight = m.where(room > 1e-9, 0.0)
        if weight.sum() <= 0:
            break
        m = m + (gap * weight / weight.sum()).clip(upper=room)
    m = m.round(1)
    room = (cap - m) if float(m.sum()) < total else m
    m.loc[room.idxmax()] = round(float(m.loc[room.idxmax()]) + total - float(m.sum()), 1)
    return m


def _names(players: pd.DataFrame) -> dict[str, str]:
    """SportsGameOdds player id -> the players file's name (its sgo_player_id column, then the
    id overrides), so a scenario row finds its 2025-26 prior even when the box score spells the
    name differently."""
    out = {}
    if "sgo_player_id" in players.columns:
        out.update({pid: n for n, pid in zip(players.player, players.sgo_player_id) if isinstance(pid, str) and pid})
    out.update({pid: n for n, pid in load_overrides().items() if isinstance(pid, str) and pid})
    return out


def build(box: pd.DataFrame, team: str, players: pd.DataFrame | None = None) -> pd.DataFrame | None:
    """The `auto` rotation for `team` from box scores (features.history's player lines): player,
    proj_mpg (summing to 240), player_id, games. None when the team has fewer than
    AUTO_MIN_GAMES games stored."""
    players = load_players() if players is None else players
    mine = box[(box.team == team) & box.minutes.notna()] if len(box) else box
    if mine.empty:
        return None
    games = (mine.drop_duplicates("event_id").sort_values("starts_at", ascending=False).event_id.head(AUTO_WINDOW))
    if len(games) < AUTO_MIN_GAMES:
        return None
    part = mine[mine.event_id.isin(set(games))]
    recent = set(games.head(AUTO_GONE_AFTER))
    active = set(part[part.event_id.isin(recent) & (part.minutes > 0)].player_id)
    agg = part.groupby("player_id").agg(box_name=("player_name", "first"), total=("minutes", "sum"),
                                        played=("minutes", lambda m: int((m > 0).sum()))).reset_index()
    agg["proj_mpg"] = agg.total / len(games)
    agg = agg[agg.player_id.isin(active) & (agg.proj_mpg >= AUTO_MIN_MPG)]
    if agg.empty:
        return None
    names = _names(players)
    by_key = {name_key(n): n for n in players.player}
    agg["player"] = [names.get(pid) or by_key.get(name_key(n)) or n for pid, n in zip(agg.player_id, agg.box_name)]
    agg = agg.drop_duplicates("player").reset_index(drop=True)
    agg["proj_mpg"] = to_total(agg.proj_mpg)
    out = agg.rename(columns={"played": "games"})[["player", "proj_mpg", "player_id", "games"]]
    return out.sort_values(["proj_mpg", "player"], ascending=[False, True]).reset_index(drop=True)


def day_scenario(team: str, d: date, scenarios_dir: Path | None = None) -> str | None:
    """A hand-built scenario for date `d` (report_MMDD, report_MMDD_b, ...): the last one written."""
    if scenario_path(team, scenarios_dir) is None:
        return None
    prefix = f"report_{d:%m%d}"
    names = list(dict.fromkeys(load_scenarios(team, scenarios_dir).scenario))
    hits = [s for s in names if s == prefix or s.startswith(prefix + "_")]
    return hits[-1] if hits else None


def fallback(team: str, scenarios_dir: Path | None = None) -> str:
    """With too few games stored: the team's latest committed report_* scenario, else full_strength."""
    if scenario_path(team, scenarios_dir) is None:
        return "full_strength"
    names = list(dict.fromkeys(load_scenarios(team, scenarios_dir).scenario))
    reports = [s for s in names if s.startswith("report_")]
    return reports[-1] if reports else ("full_strength" if "full_strength" in names else names[-1])


def write(team: str, rows: pd.DataFrame, scenarios_dir: Path | None = None) -> Path:
    """Replace the team's `auto` scenario in scenarios/TEAM.csv (created from the catalog's
    full_strength when the team has no reviewed file)."""
    scenarios_dir = scenarios_dir or config.SCENARIOS_DIR
    path = scenarios_dir / f"{team}.csv"
    if path.exists():
        df = pd.read_csv(path)
    else:
        source = scenario_path(team, scenarios_dir)
        df = pd.read_csv(source) if source is not None else pd.DataFrame(columns=["scenario", "player", "proj_mpg"])
        df = df[df.scenario == "full_strength"]
    df = df[df.scenario != AUTO]
    new = rows[["player", "proj_mpg"]].assign(scenario=AUTO)[["scenario", "player", "proj_mpg"]]
    pd.concat([df, new], ignore_index=True).to_csv(path, index=False, float_format="%.1f")
    return path


def choose(box: pd.DataFrame, teams: list[str], d: date, scenarios_dir: Path | None = None,
           players: pd.DataFrame | None = None) -> tuple[dict[str, str], list[str]]:
    """team -> scenario for the day, writing `auto` where it's built; plus one note per team."""
    players = load_players() if players is None else players
    choice, notes = {}, []
    for team in sorted(set(teams)):
        manual = day_scenario(team, d, scenarios_dir)
        if manual:
            choice[team] = manual
            notes.append(f"{team}: hand-built {manual}")
            continue
        rows = build(box, team, players)
        if rows is None:
            choice[team] = fallback(team, scenarios_dir)
            notes.append(f"{team}: under {AUTO_MIN_GAMES} games stored, keeping {choice[team]}")
            continue
        write(team, rows, scenarios_dir)
        choice[team] = AUTO
        top = ", ".join(f"{r.player} {r.proj_mpg:g}" for r in rows.head(5).itertuples())
        notes.append(f"{team}: auto, {len(rows)} players ({top}, ...)")
    return choice, notes
