"""Read-only international Polymarket (polymarket.com) NBA player points: REFERENCE ONLY.

The international exchange is close-only for US persons (docs.polymarket.com
geoblock: "Users can close existing positions but cannot open new ones"), and
every NBA points market there carries `restricted: true`. Rohan trades
Polymarket US (polymarket_us.py), a separate CFTC-regulated book, so these
prices are logged as `polymarket_intl` and never made actionable.

Each game is a Gamma event (slug nba-bos-det-2026-10-20) with player props such
as "Jayson Tatum: Points O/U 26.5" (sportsMarketType "points"). A player who
does not take the court resolves NO here (unlike Kalshi and Polymarket US).
Fees: feeSchedule {rate 0.05, exponent 1}, feeType sports_fees_v3; the legacy
takerBaseFee (1000) is ignored. Public Gamma and CLOB reads only: no wallet,
no key, no order endpoint (hard rule 4).
"""
from __future__ import annotations

import json
import re
from datetime import date

import pandas as pd
import requests

from .config import TEAM_NICKNAMES
from .players import name_key

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
HEADERS = {"User-Agent": "cold-start-usage-research/1.0"}
VENUE = "polymarket_intl"
POINTS_RE = re.compile(r"^(?P<name>.+?):\s*Points O/U\s*(?P<line>\d+(?:\.\d+)?)\s*$", re.I)
KNOWN_FEE_TYPES = {"sports_fees_v3"}
NICK = {abbr: nick.title() for nick, abbr in TEAM_NICKNAMES.items()}
NICK.update({"POR": "Trail Blazers", "PHI": "76ers"})
COLUMNS = ["venue", "ticker", "event_ticker", "player", "key", "team", "threshold", "line",
           "yes_bid", "yes_ask", "no_bid", "no_ask", "yes_ask_size", "no_ask_size", "volume",
           "fee_rate", "token_yes", "token_no", "parse_error"]


def find_game(away: str, home: str, d: date, session: requests.Session | None = None) -> dict | None:
    """The Gamma event for one game, by its slug (nba-{away}-{home}-{ET date}, lower case)."""
    session = session or requests.Session()
    slug = f"nba-{away.lower()}-{home.lower()}-{d.isoformat()}"
    resp = session.get(f"{GAMMA}/events", params={"slug": slug}, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    events = resp.json() or []
    return events[0] if events else None


def fee_rate(market: dict) -> tuple[float | None, str | None]:
    """(rate, error). fee = rate x C x p x (1 - p); unknown schedules are refused, not guessed."""
    sched = market.get("feeSchedule") or {}
    if not market.get("feesEnabled", True):
        return 0.0, None
    if market.get("feeType") not in KNOWN_FEE_TYPES or not sched:
        return None, f"unknown fee schedule {market.get('feeType')!r}"
    if float(sched.get("exponent", 1)) != 1:
        return None, f"fee exponent {sched.get('exponent')}"
    return float(sched.get("rate")), None


def token_map(market: dict) -> tuple[str | None, str | None, str | None]:
    """(yes_token, no_token, error), mapped by the outcome labels: never assume index 0 is YES."""
    try:
        outcomes = json.loads(market.get("outcomes") or "[]")
        tokens = json.loads(market.get("clobTokenIds") or "[]")
    except (TypeError, ValueError):
        return None, None, "unreadable outcomes / clobTokenIds"
    labels = [str(o).strip().lower() for o in outcomes]
    if len(tokens) != 2 or sorted(labels) not in (["no", "yes"], ["over", "under"]):
        return None, None, f"unexpected outcomes {outcomes}"
    yes_label = "yes" if "yes" in labels else "over"
    i = labels.index(yes_label)
    return tokens[i], tokens[1 - i], None


def _f(x) -> float | None:
    return None if x in (None, "") else float(x)


def points_markets(event: dict) -> pd.DataFrame:
    rows = []
    for m in event.get("markets") or []:
        question = (m.get("question") or "").strip()
        hit = POINTS_RE.match(question)
        if not hit or m.get("closed"):
            continue
        rate, fee_err = fee_rate(m)
        yes_tok, no_tok, tok_err = token_map(m)
        error = fee_err or tok_err or (None if m.get("acceptingOrders", True) else "not accepting orders")
        bid, ask = _f(m.get("bestBid")), _f(m.get("bestAsk"))
        rows.append({
            "venue": VENUE, "ticker": m.get("slug") or str(m.get("id")), "event_ticker": event.get("slug"),
            "player": hit["name"].strip(), "key": name_key(hit["name"]), "team": None, "threshold": None,
            "line": float(hit["line"]), "yes_bid": bid, "yes_ask": ask,
            "no_bid": None if ask is None else round(1 - ask, 4), "no_ask": None if bid is None else round(1 - bid, 4),
            "yes_ask_size": None, "no_ask_size": None, "volume": _f(m.get("volumeNum")),
            "fee_rate": rate, "token_yes": yes_tok, "token_no": no_tok, "parse_error": error,
        })
    return pd.DataFrame(rows, columns=COLUMNS)


def book(yes_token: str, session: requests.Session | None = None) -> dict[str, list[tuple[float, float]]]:
    """Ask ladders for both sides from the YES token's CLOB book, cheapest first.
    The NO book mirrors it: a YES bid at p is a NO offer at 1 - p."""
    session = session or requests.Session()
    resp = session.get(f"{CLOB}/book", params={"token_id": yes_token}, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    b = resp.json()
    yes = sorted(((float(a["price"]), float(a["size"])) for a in b.get("asks") or []), key=lambda x: x[0])
    no = sorted(((round(1 - float(x["price"]), 4), float(x["size"])) for x in b.get("bids") or []), key=lambda x: x[0])
    return {"YES": yes, "NO": no}
