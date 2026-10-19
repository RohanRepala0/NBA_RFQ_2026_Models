"""Map stats-sheet player names to SportsGameOdds playerIDs (e.g. LEBRON_JAMES_1_NBA).

Order of precedence: explicit `sgo_player_id` column in the players CSV, then
data/player_id_overrides.csv, then a normalized-name match against the event's
roster (same team first). Ambiguous or missing matches are reported, never guessed.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pandas as pd

from .config import PLAYER_ID_OVERRIDES_CSV

SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}


def name_key(name: str) -> str:
    name = re.sub(r'["\u201c\u201d][^"\u201c\u201d]*["\u201c\u201d]', " ", str(name))   # drop quoted nicknames
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = s.replace("'", "").replace(".", "")
    tokens = [t for t in re.findall(r"[a-z0-9]+", s) if t not in SUFFIXES]
    return "".join(tokens)


def name_from_player_id(player_id: str) -> str:
    """LEBRON_JAMES_1_NBA -> 'Lebron James' (good enough for matching)."""
    core = re.sub(r"_\d+_[A-Z]+$", "", str(player_id))
    return " ".join(t.capitalize() for t in core.split("_") if t)


def load_overrides(path: Path = PLAYER_ID_OVERRIDES_CSV) -> dict[str, str]:
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    return dict(zip(df.player, df.sgo_player_id))


def candidates_for_event(roster: pd.DataFrame, odds_player_ids: list[str]) -> pd.DataFrame:
    """Event roster (player_id, name, team_abbr) plus any player IDs seen only in odds."""
    cols = ["player_id", "name", "team_abbr"]
    roster = roster[cols] if not roster.empty else pd.DataFrame(columns=cols)
    known = set(roster.player_id)
    extra = pd.DataFrame([{"player_id": p, "name": name_from_player_id(p), "team_abbr": None}
                          for p in sorted(set(odds_player_ids) - known)], columns=cols)
    return pd.concat([roster, extra], ignore_index=True).drop_duplicates("player_id")


def map_players(names: list[str], candidates: pd.DataFrame, team: str | None = None,
                explicit: dict[str, str] | None = None,
                overrides: dict[str, str] | None = None) -> tuple[dict[str, str | None], list[str]]:
    explicit = {k: v for k, v in (explicit or {}).items() if isinstance(v, str) and v}
    overrides = load_overrides() if overrides is None else overrides
    keyed = candidates.assign(key=candidates.name.map(name_key))
    out: dict[str, str | None] = {}
    problems: list[str] = []
    for name in names:
        if name in explicit:
            out[name] = explicit[name]
            continue
        if name in overrides:
            out[name] = overrides[name]
            continue
        hits = keyed[keyed.key == name_key(name)]
        if team is not None and len(hits) > 1:
            same_team = hits[hits.team_abbr == team]
            hits = same_team if len(same_team) else hits
        if len(hits) == 1:
            out[name] = hits.player_id.iloc[0]
            row = hits.iloc[0]
            if team and row.team_abbr and row.team_abbr != team:
                problems.append(f"{name}: matched {row.player_id} but roster says {row.team_abbr}, not {team}")
        else:
            out[name] = None
            problems.append(f"{name}: {'ambiguous' if len(hits) > 1 else 'no'} match on the event roster"
                            " (add a row to data/player_id_overrides.csv)")
    return out, problems
