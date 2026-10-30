"""Read-only Polymarket US: the CFTC-regulated US exchange Rohan can actually trade.

Separate from polymarket.com (different IDs, slugs and order books). Public,
keyless market data lives on https://gateway.polymarket.us (25 requests/s;
503 during the Thursday 6-8am ET maintenance window). The authenticated
trading host api.polymarket.us is never called (hard rule 4).

- Game events: /v1/events/slug/nba-{away}-{home}-{ET date}, with US team codes
  (ny, sa, gs, no, pho for NYK, SAS, GSW, NOP, PHX; others lower case).
- Player props are "N+" ladders, one sportsMarketType per stat
  (config.PM_US_STAT_TYPES: basketball_player_points / _rebounds / _assists, and the shadow
  stats' _threes / _steals / _blocks / _points_rebounds_assists).
  NBA wording: "Will Jaylen Brown record at least 10 total rebounds in ...?",
  title "Jaylen Brown 10+ rebounds", line 10 (= 10 or more); points and assists
  read the same way ("at least 30 points", "at least 5 assists"). YES is the
  `long` side, and each side carries the player's team abbreviation. Lines can
  be any integer (points step by 5, rebounds and assists by 1-2), and an O/U
  X.5 line is handled too. The numeric `line` and sportsMarketType are trusted
  over any text, and a stat word that disagrees with the type is a parse error.
- The docs say slugs are not part of the public contract: games are found by
  slug first, then by teams and start date in the league's event list.
- Book: /v1/markets/{slug}/book. `offers` are YES asks (ascending); a bid at p
  is a NO offer at 1 - p.
- Fee: feeCoefficient (0.0695) x C x p x (1 - p), rounded per order to the cent.
- A player who never plays settles at the last fair market price (LFMP).
"""
from __future__ import annotations

import re
from datetime import date

import pandas as pd
import requests

from . import config
from .players import name_key

GATEWAY = "https://gateway.polymarket.us"
HEADERS = {"User-Agent": "cold-start-usage-research/1.0"}
VENUE = "polymarket_us"
US_TEAM = {"NYK": "ny", "SAS": "sa", "GSW": "gs", "NOP": "no", "PHX": "pho"}
STAT_WORD = (r"(?:total\s+|combined\s+)?(?P<word>points,\s+rebounds,?\s+and\s+assists|three-point field goals?(?: made)?"
             r"|threes?|points?|rebounds?|assists?|steals?|blocks?)\b")
# A question's stat words -> our stat ("at least 15 combined points, rebounds and assists" is pra).
WORD_STAT = {"point": "points", "rebound": "rebounds", "assist": "assists", "steal": "steals", "block": "blocks",
             "three": "threes", "three-point field goals made": "threes", "three-point field goal made": "threes",
             "three-point field goals": "threes", "three-point field goal": "threes"}


def word_stat(word: str) -> str | None:
    w = " ".join(word.lower().split())
    if w.startswith("points, rebounds"):
        return "pra"
    return WORD_STAT.get(w) or WORD_STAT.get(w.rstrip("s"))
QUESTION_RE = re.compile(r"^Will (?P<name>.+?) (?:record|score)(?: at least| over)? (?P<n>\d+(?:\.\d+)?)\+? "
                         + STAT_WORD, re.I)
TITLE_RE = re.compile(r"^(?P<name>.+?):?\s+(?:(?:over|o)\s*)?(?P<n>\d+(?:\.\d+)?)\+?\s+" + STAT_WORD, re.I)
FROM_US = {v: k for k, v in US_TEAM.items()}
COLUMNS = ["venue", "ticker", "event_ticker", "stat", "player", "key", "team", "threshold", "line",
           "yes_bid", "yes_ask", "no_bid", "no_ask", "yes_ask_size", "no_ask_size", "volume",
           "fee_rate", "tip", "parse_error"]


def slug(away: str, home: str, d: date) -> str:
    code = lambda t: US_TEAM.get(t, t.lower())  # noqa: E731
    return f"nba-{code(away)}-{code(home)}-{d.isoformat()}"


def _get(session: requests.Session, path: str, params: dict | None = None) -> dict:
    resp = session.get(f"{GATEWAY}{path}", params=params, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.json()


def team_code(us_abbr: str | None) -> str | None:
    return None if not us_abbr else FROM_US.get(us_abbr.lower(), us_abbr.upper())


def find_game(away: str, home: str, d: date, session: requests.Session | None = None) -> dict | None:
    """The full event (with props) for one game: by slug, else by teams and ET date."""
    session = session or requests.Session()
    try:
        return _get(session, f"/v1/events/slug/{slug(away, home, d)}").get("event")
    except requests.HTTPError as exc:
        if exc.response is None or exc.response.status_code != 404:
            raise
    from .schedule import et_date
    listing = _get(session, "/v2/leagues/nba/events", {"limit": 100}).get("events") or []
    for ev in listing:
        teams = {team_code(t.get("abbreviation")) for t in ev.get("teams") or [] if isinstance(t, dict)}
        start = ev.get("startTime")
        if teams == {away, home} and start and et_date(pd.Timestamp(start).tz_convert("UTC").tz_localize(None)) == d:
            return _get(session, f"/v1/events/slug/{ev['slug']}").get("event")
    return None


def _px(q) -> float | None:
    if isinstance(q, dict):
        q = q.get("value")
    return None if q in (None, "") else float(q)


def prop_markets(event: dict, stats: tuple[str, ...] = config.STATS) -> pd.DataFrame:
    """One row per player-prop market of the given stats, with its stat from sportsMarketType.
    Rows that can't be parsed are kept with `parse_error` set."""
    rows = []
    for m in event.get("markets") or []:
        stat = config.PM_US_STAT_TYPES.get(m.get("sportsMarketType"))
        if stat not in stats:
            continue
        question, title = (m.get("question") or "").strip(), (m.get("title") or "").strip()
        hit = QUESTION_RE.match(question) or TITLE_RE.match(title)
        line_raw = m.get("line")
        error = None
        if not hit:
            error = f"unparsed question {question!r}"
        elif word_stat(hit["word"]) != stat:
            error = f"question says {hit['word']!r} but sportsMarketType is {m.get('sportsMarketType')}"
        if line_raw is None:
            error = error or "no line"
            threshold, line = None, None
        elif float(line_raw) == int(float(line_raw)):           # "N+" (gte): YES if points >= N
            threshold, line = int(float(line_raw)), float(line_raw) - 0.5
        else:                                                   # O/U X.5: YES if points > X.5
            threshold, line = None, float(line_raw)
        if hit and threshold is not None and float(hit["n"]) != threshold:
            error = error or f"question says {hit['n']}+ but line is {line_raw}"
        sides = {bool(s.get("long")): (s.get("description") or "").lower() for s in m.get("marketSides") or []}
        if sides and sides.get(True) not in ("yes", "over"):
            error = error or f"long side is {sides.get(True)!r}, not Yes/Over"
        fee = m.get("feeCoefficient")
        if fee is None:
            error = error or "no feeCoefficient"
        if m.get("status") not in (None, "MARKET_STATUS_OPEN"):
            error = error or f"status {m.get('status')}"
        bid, ask = _px(m.get("bestBidQuote")), _px(m.get("bestAskQuote"))
        name = hit["name"].strip() if hit else None
        team = next((team_code((x.get("team") or {}).get("abbreviation")) for x in m.get("marketSides") or []
                     if x.get("long") and isinstance(x.get("team"), dict)), None)
        rows.append({
            "venue": VENUE, "ticker": m.get("slug"), "event_ticker": event.get("slug"), "stat": stat,
            "player": name, "key": name_key(name) if name else None, "team": team,
            "threshold": threshold, "line": line, "yes_bid": bid, "yes_ask": ask,
            "no_bid": None if ask is None else round(1 - ask, 4), "no_ask": None if bid is None else round(1 - bid, 4),
            "yes_ask_size": None, "no_ask_size": None, "volume": None,
            "fee_rate": None if fee is None else float(fee),
            "tip": None if not m.get("gameStartTime") else pd.Timestamp(m["gameStartTime"]).tz_convert("UTC").tz_localize(None),
            "parse_error": error,
        })
    return pd.DataFrame(rows, columns=COLUMNS)


def points_markets(event: dict) -> pd.DataFrame:
    """Player points markets only (prop_markets for one stat)."""
    return prop_markets(event, ("points",))


def book_from_response(body: dict) -> dict[str, list[tuple[float, float]]]:
    md = body.get("marketData") or {}
    yes = sorted(((_px(o.get("px")), float(o.get("qty") or 0)) for o in md.get("offers") or []), key=lambda x: x[0])
    no = sorted(((round(1 - _px(b.get("px")), 4), float(b.get("qty") or 0)) for b in md.get("bids") or []),
                key=lambda x: x[0])
    return {"YES": [lv for lv in yes if lv[1] > 0], "NO": [lv for lv in no if lv[1] > 0]}


def book(market_slug: str, session: requests.Session | None = None) -> dict[str, list[tuple[float, float]]]:
    return book_from_response(_get(session or requests.Session(), f"/v1/markets/{market_slug}/book"))


def settlement(market_slug: str, session: requests.Session | None = None) -> float | None:
    """Settlement value of YES (1, 0, or a fair price), or None while unsettled."""
    try:
        body = _get(session or requests.Session(), f"/v1/markets/{market_slug}/settlement")
    except requests.HTTPError:
        return None
    value = body.get("settlement")
    return None if value is None else float(value)
