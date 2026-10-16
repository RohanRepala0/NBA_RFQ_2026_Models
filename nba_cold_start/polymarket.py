"""Read-only Polymarket market data for NBA player points.

Polymarket lists each NBA game as an event (slug like `nba-bos-det-2026-10-20`)
holding moneyline, spread and total markets plus a few player props such as
"Jayson Tatum: Points O/U 26.5" (sportsMarketType "points", YES = over).
Public Gamma and CLOB read endpoints only: no wallet, no key, no order
endpoint is ever called (hard rule 4).
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
HEADERS = {"User-Agent": "nba-cold-start-research/1.0"}
POINTS_RE = re.compile(r"^(?P<name>.+?):\s*Points O/U\s*(?P<line>\d+(?:\.\d+)?)\s*$", re.I)
NICK = {abbr: nick.title() for nick, abbr in TEAM_NICKNAMES.items()}
NICK.update({"POR": "Trail Blazers", "PHI": "76ers"})


def find_game(away: str, home: str, d: date, session: requests.Session | None = None) -> dict | None:
    """The Polymarket event for one game, found by team nicknames and the ET date in its slug."""
    session = session or requests.Session()
    q = f"{NICK.get(away, away)} {NICK.get(home, home)}"
    resp = session.get(f"{GAMMA}/public-search", params={"q": q, "limit_per_type": 20, "events_status": "active"},
                       headers=HEADERS, timeout=20)
    resp.raise_for_status()
    for ev in resp.json().get("events") or []:
        slug = ev.get("slug") or ""
        if slug.startswith("nba-") and slug.endswith(d.isoformat()):
            return ev
    return None


def taker_fee(price: float, fee_bps: float | None) -> float:
    """Taker fee per share: base rate (the market's takerBaseFee, in bps) x min(price, 1 - price).
    This follows Polymarket's published fee formula; re-check it against their current docs."""
    return 0.0 if not fee_bps else fee_bps / 10_000 * min(price, 1 - price)


def points_markets(event: dict) -> pd.DataFrame:
    rows = []
    for m in event.get("markets") or []:
        hit = POINTS_RE.match((m.get("question") or "").strip())
        if not hit or m.get("closed"):
            continue
        tokens = json.loads(m.get("clobTokenIds") or "[]")
        bid, ask = m.get("bestBid"), m.get("bestAsk")
        rows.append({
            "venue": "polymarket", "event": event.get("slug"), "market_id": str(m.get("id")),
            "player": hit["name"].strip(), "key": name_key(hit["name"]), "line": float(hit["line"]),
            "yes_bid": None if bid is None else 100 * float(bid), "yes_ask": None if ask is None else 100 * float(ask),
            "no_bid": None if ask is None else 100 * (1 - float(ask)), "no_ask": None if bid is None else 100 * (1 - float(bid)),
            "token_yes": tokens[0] if tokens else None, "token_no": tokens[1] if len(tokens) > 1 else None,
            "fee_bps": float(m.get("takerBaseFee") or 0) if m.get("feesEnabled") else 0.0,
        })
    return pd.DataFrame(rows)


def asks(token_id: str, session: requests.Session | None = None) -> list[tuple[float, float]]:
    """Ask side of the order book as (price in dollars, size in shares), cheapest first."""
    session = session or requests.Session()
    resp = session.get(f"{CLOB}/book", params={"token_id": token_id}, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    book = resp.json()
    return sorted(((float(a["price"]), float(a["size"])) for a in book.get("asks") or []), key=lambda x: x[0])
