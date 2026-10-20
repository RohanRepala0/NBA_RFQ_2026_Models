"""Turn allowlist-filtered SportsGameOdds events into table rows.

Player props kept: full-game over/unders on config.STATS (points, rebounds,
assists), one row per book and side with its stat. Combo markets
(points+rebounds+assists and the like) are other statIDs and never match.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from . import config
from .config import book_role, is_allowed_book, team_abbr
from .odds_math import parse_american
from .storage import Storage, to_naive_utc

STAT_ODD_RE = re.compile(rf"^(?P<stat>{'|'.join(config.STATS)})-(?P<player>.+_NBA)-game-ou-(?P<side>over|under)$")
TEAM_ENTITIES = {"home", "away", "all"}


def player_stat_side(odd_id: str, odd: dict) -> tuple[str, str, str] | None:
    """(player_id, stat, side) if this odd is a full-game player over/under on one of config.STATS."""
    if odd.get("statID") is not None:
        if (odd.get("statID") in config.STATS and odd.get("periodID") == "game"
                and odd.get("betTypeID") == "ou" and odd.get("sideID") in ("over", "under")):
            player = odd.get("playerID") or odd.get("statEntityID")
            if player and player not in TEAM_ENTITIES:
                return player, odd["statID"], odd["sideID"]
        return None
    m = STAT_ODD_RE.match(odd_id)
    return (m["player"], m["stat"], m["side"]) if m else None


def player_points_side(odd_id: str, odd: dict) -> tuple[str, str] | None:
    """(player_id, side) if this odd is a full-game player points over/under."""
    hit = player_stat_side(odd_id, odd)
    return (hit[0], hit[2]) if hit and hit[1] == "points" else None


def _float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _price(value) -> float | None:
    try:
        return parse_american(value)
    except (TypeError, ValueError):
        return None


def event_row(event: dict, ts: datetime, tag: str) -> dict:
    teams = event.get("teams") or {}
    status = event.get("status") or {}
    home = (teams.get("home") or {}).get("teamID")
    away = (teams.get("away") or {}).get("teamID")
    return {
        "ts": ts, "event_id": event["eventID"], "starts_at": to_naive_utc(status.get("startsAt")),
        "home_team_id": home, "away_team_id": away,
        "home_abbr": team_abbr(home), "away_abbr": team_abbr(away),
        "cancelled": bool(status.get("cancelled")), "started": bool(status.get("started")),
        "finalized": bool(status.get("finalized")), "snapshot_tag": tag,
    }


def player_rows(event: dict, ts: datetime) -> list[dict]:
    rows = []
    for pid, p in (event.get("players") or {}).items():
        rows.append({
            "ts": ts, "event_id": event["eventID"], "player_id": p.get("playerID", pid),
            "team_id": p.get("teamID"), "team_abbr": team_abbr(p.get("teamID")),
            "name": p.get("name") or " ".join(x for x in (p.get("firstName"), p.get("lastName")) if x),
            "status": p.get("status"),
        })
    return rows


def quote_rows(event: dict, ts: datetime, tag: str) -> list[dict]:
    rows = []
    for odd_id, odd in (event.get("odds") or {}).items():
        hit = player_stat_side(odd_id, odd)
        if not hit:
            continue
        player_id, stat, side = hit
        for book, q in (odd.get("byBookmaker") or {}).items():
            if not is_allowed_book(book):      # defense in depth; the client already filtered
                continue
            rows.append({
                "ts": ts, "event_id": event["eventID"], "odd_id": odd_id,
                "player_id": player_id, "stat": stat, "side": side, "book": book.lower(),
                "book_role": book_role(book), "line": _float(q.get("overUnder")),
                "odds_american": _price(q.get("odds")), "available": bool(q.get("available", False)),
                "is_main_line": q.get("isMainLine", True) is not False,
                "quote_ts": to_naive_utc(q.get("lastUpdatedAt")), "snapshot_tag": tag,
            })
    return rows


def books_seen_rows(event: dict, ts: datetime) -> list[dict]:
    """posts_player_points keeps its meaning: the book posted player points on this call."""
    books: dict[str, bool] = {}
    for odd_id, odd in (event.get("odds") or {}).items():
        points = player_points_side(odd_id, odd) is not None
        for book in (odd.get("byBookmaker") or {}):
            if is_allowed_book(book):
                books[book.lower()] = books.get(book.lower(), False) or points
    return [{"ts": ts, "event_id": event["eventID"], "book": b, "book_role": book_role(b),
             "posts_player_points": pts} for b, pts in sorted(books.items())]


def player_stat_results(event: dict) -> dict[str, dict[str, float]]:
    """player_id -> {stat: actual full-game value} for config.STATS, from
    results.game.<playerID>.<stat> (fallback: the ended odd's score). Overtime counts."""
    out: dict[str, dict[str, float]] = {}
    for entity, stats in ((event.get("results") or {}).get("game") or {}).items():
        if entity in TEAM_ENTITIES or not isinstance(stats, dict):
            continue
        for stat in config.STATS:
            if stats.get(stat) is not None:
                out.setdefault(entity, {})[stat] = float(stats[stat])
    for odd_id, odd in (event.get("odds") or {}).items():
        hit = player_stat_side(odd_id, odd)
        if hit and hit[1] not in out.get(hit[0], {}) and odd.get("score") is not None and odd.get("ended"):
            out.setdefault(hit[0], {})[hit[1]] = float(odd["score"])
    return out


def player_points_results(event: dict) -> dict[str, float]:
    """player_id -> actual full-game points, from results (fallback: the odd's score)."""
    return {pid: s["points"] for pid, s in player_stat_results(event).items() if "points" in s}


def store_snapshot(storage: Storage, events: list[dict], ts: datetime, tag: str | dict) -> dict:
    """Append one snapshot. `tag` may be a dict event_id -> tag."""
    counts = {"events": 0, "event_players": 0, "odds_snapshots": 0, "books_seen": 0}
    for ev in events:
        t = tag.get(ev["eventID"], "adhoc") if isinstance(tag, dict) else tag
        counts["events"] += storage.append("events", [event_row(ev, ts, t)])
        counts["event_players"] += storage.append("event_players", player_rows(ev, ts))
        counts["odds_snapshots"] += storage.append("odds_snapshots", quote_rows(ev, ts, t))
        counts["books_seen"] += storage.append("books_seen", books_seen_rows(ev, ts))
    return counts


def save_raw(events: list[dict], ts: datetime, label: str, raw_dir: Path | None = None) -> Path:
    """Keep our own history (the free plan has none). Events are already allowlist-filtered."""
    day_dir = (raw_dir or config.RAW_DIR) / ts.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / f"{ts.strftime('%H%M%S')}_{label}.json"
    path.write_text(json.dumps({"fetched_at": ts.isoformat() + "Z", "data": events}, indent=1, sort_keys=True))
    return path
