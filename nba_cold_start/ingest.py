"""Turn allowlist-filtered SportsGameOdds events into table rows."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from . import config
from .config import book_role, is_allowed_book, team_abbr
from .odds_math import parse_american
from .storage import Storage, to_naive_utc

POINTS_ODD_RE = re.compile(r"^points-(?P<player>.+_NBA)-game-ou-(?P<side>over|under)$")
TEAM_ENTITIES = {"home", "away", "all"}


def player_points_side(odd_id: str, odd: dict) -> tuple[str, str] | None:
    """(player_id, side) if this odd is a full-game player points over/under."""
    if odd.get("statID") is not None:
        if (odd.get("statID") == "points" and odd.get("periodID") == "game"
                and odd.get("betTypeID") == "ou" and odd.get("sideID") in ("over", "under")):
            player = odd.get("playerID") or odd.get("statEntityID")
            if player and player not in TEAM_ENTITIES:
                return player, odd["sideID"]
        return None
    m = POINTS_ODD_RE.match(odd_id)
    return (m["player"], m["side"]) if m else None


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
        hit = player_points_side(odd_id, odd)
        if not hit:
            continue
        player_id, side = hit
        for book, q in (odd.get("byBookmaker") or {}).items():
            if not is_allowed_book(book):      # defense in depth; the client already filtered
                continue
            rows.append({
                "ts": ts, "event_id": event["eventID"], "odd_id": odd_id,
                "player_id": player_id, "side": side, "book": book.lower(),
                "book_role": book_role(book), "line": _float(q.get("overUnder")),
                "odds_american": _price(q.get("odds")), "available": bool(q.get("available", False)),
                "is_main_line": q.get("isMainLine", True) is not False,
                "quote_ts": to_naive_utc(q.get("lastUpdatedAt")), "snapshot_tag": tag,
            })
    return rows


def books_seen_rows(event: dict, ts: datetime) -> list[dict]:
    books: dict[str, bool] = {}
    for odd_id, odd in (event.get("odds") or {}).items():
        points = player_points_side(odd_id, odd) is not None
        for book in (odd.get("byBookmaker") or {}):
            if is_allowed_book(book):
                books[book.lower()] = books.get(book.lower(), False) or points
    return [{"ts": ts, "event_id": event["eventID"], "book": b, "book_role": book_role(b),
             "posts_player_points": pts} for b, pts in sorted(books.items())]


def player_points_results(event: dict) -> dict[str, float]:
    """player_id -> actual full-game points, from results (fallback: the odd's score)."""
    out: dict[str, float] = {}
    for entity, stats in ((event.get("results") or {}).get("game") or {}).items():
        if entity not in TEAM_ENTITIES and isinstance(stats, dict) and "points" in stats:
            out[entity] = float(stats["points"])
    for odd_id, odd in (event.get("odds") or {}).items():
        hit = player_points_side(odd_id, odd)
        if hit and hit[0] not in out and odd.get("score") is not None and odd.get("ended"):
            out[hit[0]] = float(odd["score"])
    return out


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
