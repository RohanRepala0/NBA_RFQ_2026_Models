"""Synthetic SportsGameOdds /events payloads (shape per openapi.json v2). NOT real odds.

The matchup and player IDs are real (MIN @ MIA, Oct 21 2026, IDs from GET
/players); every line, price and result is invented.

Built-in traps the tests rely on:
- every market also carries OFF_LIST_BOOK, which must never reach storage,
  the consensus, the raw cache or stdout;
- precomputed consensus fields (fairOverUnder, bookOdds, ...) are set to
  absurd values, so any accidental use shows up in the numbers;
- one stale quote (Larsson at caesars), one DFS placeholder (prizepicks),
  one player with a single priced book (Dru Smith), one projected player with
  no market (Nick Richards), and Kalshi quotes on two players.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

OFF_LIST_BOOK = "offlistbook"
EVENT_ID = "SYNTHETIC_MIN_MIA_20261021"
TIP = datetime(2026, 10, 21, 23, 30)         # 7:30 PM ET
FETCHED = TIP - timedelta(minutes=60)        # a T-60m snapshot

ROSTER = {
    "GIANNIS_ANTETOKOUNMPO_1_NBA": ("Giannis Antetokounmpo", "MIA"),
    "BAM_ADEBAYO_1_NBA": ("Bam Adebayo", "MIA"),
    "ANDREW_WIGGINS_1_NBA": ("Andrew Wiggins", "MIA"),
    "DAVION_MITCHELL_1_NBA": ("Davion Mitchell", "MIA"),
    "TIM_HARDAWAY_JR_1_NBA": ("Tim Hardaway Jr.", "MIA"),
    "PELLE_LARSSON_1_NBA": ("Pelle Larsson", "MIA"),
    "BOBBY_PORTIS_1_NBA": ("Bobby Portis", "MIA"),
    "NIKOLA_JOVIC_1_NBA": ("Nikola Jović", "MIA"),
    "SIMONE_FONTECCHIO_1_NBA": ("Simone Fontecchio", "MIA"),
    "NICK_RICHARDS_1_NBA": ("Nick Richards", "MIA"),
    "DRU_SMITH_1_NBA": ("Dru Smith", "MIA"),
    "ANTHONY_EDWARDS_1_NBA": ("Anthony Edwards", "MIN"),
}
TEAM_IDS = {"MIA": "MIAMI_HEAT_NBA", "MIN": "MINNESOTA_TIMBERWOLVES_NBA"}

# player -> {book: (line, over, under)}
LINES = {
    "GIANNIS_ANTETOKOUNMPO_1_NBA": {"draftkings": (29.5, -110, -110), "betmgm": (29.5, -115, -105),
                                    "caesars": (30.5, +105, -125), "espnbet": (29.5, -112, -108)},
    "BAM_ADEBAYO_1_NBA": {"draftkings": (18.5, -110, -110), "espnbet": (18.5, -105, -115),
                          "bovada": (18.5, -115, -105)},
    "ANDREW_WIGGINS_1_NBA": {"draftkings": (14.5, -110, -110), "betmgm": (13.5, +110, -130),
                             "espnbet": (14.5, -105, -115)},
    "DAVION_MITCHELL_1_NBA": {"draftkings": (8.5, -110, -110), "espnbet": (8.5, -115, -105)},
    "TIM_HARDAWAY_JR_1_NBA": {"draftkings": (12.5, -110, -110), "betmgm": (12.5, -105, -115),
                              "espnbet": (12.5, -110, -110)},
    "PELLE_LARSSON_1_NBA": {"draftkings": (9.5, -115, -105), "caesars": (9.5, -110, -110)},
    "BOBBY_PORTIS_1_NBA": {"draftkings": (11.5, -110, -110), "espnbet": (11.5, -120, +100)},
    "NIKOLA_JOVIC_1_NBA": {"draftkings": (6.5, -110, -110), "betmgm": (6.5, -110, -110)},
    "SIMONE_FONTECCHIO_1_NBA": {"draftkings": (7.5, -125, +105), "espnbet": (7.5, -120, +100)},
    "DRU_SMITH_1_NBA": {"draftkings": (3.5, -110, -110)},
    "ANTHONY_EDWARDS_1_NBA": {"draftkings": (27.5, -110, -110), "espnbet": (27.5, -104, -116)},
}
STALE = {("PELLE_LARSSON_1_NBA", "caesars"): 45}           # minutes old at fetch
KALSHI = {"GIANNIS_ANTETOKOUNMPO_1_NBA": (29.5, +105, -125), "BAM_ADEBAYO_1_NBA": (18.5, -105, -115)}
ACTUAL_POINTS = {"GIANNIS_ANTETOKOUNMPO_1_NBA": 31, "BAM_ADEBAYO_1_NBA": 17, "ANDREW_WIGGINS_1_NBA": 12,
                 "DAVION_MITCHELL_1_NBA": 9, "TIM_HARDAWAY_JR_1_NBA": 15, "PELLE_LARSSON_1_NBA": 8,
                 "BOBBY_PORTIS_1_NBA": 13, "NIKOLA_JOVIC_1_NBA": 4, "SIMONE_FONTECCHIO_1_NBA": 7,
                 "NICK_RICHARDS_1_NBA": 2, "ANTHONY_EDWARDS_1_NBA": 30}   # Dru Smith: DNP


def _iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _fmt(odds: int) -> str:
    return f"+{odds}" if odds > 0 else str(odds)


def _odd(pid: str, side: str, quotes: dict, fetched: datetime, final: bool) -> dict:
    other = "under" if side == "over" else "over"
    by_book = {}
    for book, (line, over, under) in quotes.items():
        age = STALE.get((pid, book), 4)
        by_book[book] = {"odds": _fmt(over if side == "over" else under), "overUnder": str(line),
                         "available": not final, "lastUpdatedAt": _iso(fetched - timedelta(minutes=age)),
                         "deeplink": f"https://example.invalid/{book}/{pid}"}
    by_book["prizepicks"] = {"odds": "+100", "overUnder": str(next(iter(quotes.values()))[0]),
                             "available": not final, "lastUpdatedAt": _iso(fetched)}
    by_book[OFF_LIST_BOOK] = {"odds": "-500", "overUnder": "99.5", "available": not final,
                              "lastUpdatedAt": _iso(fetched),
                              "deeplink": f"https://{OFF_LIST_BOOK}.example.invalid/{pid}"}
    if pid in KALSHI:
        line, over, under = KALSHI[pid]
        by_book["kalshi"] = {"odds": _fmt(over if side == "over" else under), "overUnder": str(line),
                             "available": not final, "lastUpdatedAt": _iso(fetched - timedelta(minutes=2))}
    odd = {
        "oddID": f"points-{pid}-game-ou-{side}", "opposingOddID": f"points-{pid}-game-ou-{other}",
        "marketName": f"{ROSTER[pid][0]} Points Over/Under", "statID": "points",
        "statEntityID": pid, "periodID": "game", "betTypeID": "ou", "sideID": side, "playerID": pid,
        "started": final, "ended": final, "cancelled": False,
        # Precomputed consensus fields: absurd on purpose. Must be ignored.
        "fairOdds": "-900", "bookOdds": "+900", "fairOverUnder": "99.5", "bookOverUnder": "0.5",
        "bookOddsAvailable": True, "fairOddsAvailable": True, "byBookmaker": by_book,
    }
    if final and pid in ACTUAL_POINTS:
        odd["score"] = ACTUAL_POINTS[pid]
    return odd


def synthetic_event(fetched: datetime = FETCHED, final: bool = False) -> dict:
    odds = {}
    for pid, quotes in LINES.items():
        for side in ("over", "under"):
            o = _odd(pid, side, quotes, fetched, final)
            odds[o["oddID"]] = o
    event = {
        "eventID": EVENT_ID, "sportID": "BASKETBALL", "leagueID": "NBA", "type": "match",
        "info": {"seasonWeek": "1", "broadcasts": [{"broadcasterID": OFF_LIST_BOOK,
                                                    "name": f"{OFF_LIST_BOOK} network", "type": "tv"}]},
        "links": {"bookmakers": {OFF_LIST_BOOK: f"https://{OFF_LIST_BOOK}.example.invalid"}},
        "teams": {"home": {"teamID": TEAM_IDS["MIA"], "names": {"short": "MIA"}},
                  "away": {"teamID": TEAM_IDS["MIN"], "names": {"short": "MIN"}}},
        "players": {pid: {"playerID": pid, "name": name, "teamID": TEAM_IDS[team], "status": "active"}
                    for pid, (name, team) in ROSTER.items()},
        "status": {"startsAt": _iso(TIP), "started": final, "ended": final, "finalized": final,
                   "cancelled": False, "oddsAvailable": not final, "oddsPresent": True},
        "results": {}, "odds": odds,
    }
    if final:
        event["results"] = {"game": {"home": {"points": 112}, "away": {"points": 108},
                                     **{pid: {"points": pts} for pid, pts in ACTUAL_POINTS.items()}}}
    return event


def events_response(events: list[dict], next_cursor: str | None = None) -> dict:
    body = {"success": True, "data": events}
    if next_cursor:
        body["nextCursor"] = next_cursor
    return body


def write_examples(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    slate = out_dir / f"synthetic_slate_{TIP.date()}.json"
    final = out_dir / f"synthetic_final_{TIP.date()}.json"
    slate.write_text(json.dumps(events_response([synthetic_event(FETCHED)]), indent=1) + "\n")
    final.write_text(json.dumps(events_response([synthetic_event(TIP + timedelta(hours=3), final=True)]),
                                indent=1) + "\n")
    return [slate, final]


if __name__ == "__main__":
    for p in write_examples(Path(__file__).resolve().parents[2] / "examples"):
        print(f"Wrote {p}")
