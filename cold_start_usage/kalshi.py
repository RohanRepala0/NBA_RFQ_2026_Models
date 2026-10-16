"""Read-only Kalshi market data for NBA player points (series KXNBAPTS).

Kalshi lists player points as "N+ points" ladders, one market per rung
(e.g. "Paul George: 25+ points", floor_strike 24.5, strike_type "greater"),
grouped into one event per game. This module reads the public market-data
endpoint only: no account, no key, and no portfolio or order endpoint is
ever called (hard rule 4). Positions are entered by hand.
"""
from __future__ import annotations

import re
import time

import pandas as pd
import requests

from .players import name_key

BASE = "https://api.elections.kalshi.com/trade-api/v2"
SERIES = "KXNBAPTS"
TITLE_RE = re.compile(r"^(?P<name>.+?):\s*(?P<n>\d+)\+\s*points?\s*$", re.I)


def fetch_open_markets(series: str = SERIES, session: requests.Session | None = None,
                       max_pages: int = 20) -> list[dict]:
    session = session or requests.Session()
    out, cursor = [], None
    for _ in range(max_pages):
        params = {"series_ticker": series, "status": "open", "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        resp = session.get(f"{BASE}/markets", params=params, timeout=20)
        resp.raise_for_status()
        body = resp.json()
        out += body.get("markets") or []
        cursor = body.get("cursor")
        if not cursor:
            break
        time.sleep(0.2)                       # stay well under the public rate limit
    return out


def _cents(m: dict, field: str) -> float | None:
    """Kalshi reports prices in cents (`yes_ask`) and/or dollars (`yes_ask_dollars`)."""
    dollars = m.get(f"{field}_dollars")
    if dollars not in (None, ""):
        try:
            return round(float(dollars) * 100, 2)
        except (TypeError, ValueError):
            pass
    value = m.get(field)
    return None if value in (None, "") else float(value)


def parse_markets(markets: list[dict]) -> pd.DataFrame:
    rows = []
    for m in markets:
        title = m.get("title") or m.get("yes_sub_title") or ""
        hit = TITLE_RE.match(title.strip())
        if not hit:
            continue
        rows.append({
            "ticker": m.get("ticker"), "event_ticker": m.get("event_ticker"),
            "player": hit["name"].strip(), "key": name_key(hit["name"]), "threshold": int(hit["n"]),
            "yes_bid": _cents(m, "yes_bid"), "yes_ask": _cents(m, "yes_ask"),
            "no_bid": _cents(m, "no_bid"), "no_ask": _cents(m, "no_ask"),
            "volume": m.get("volume"), "close_time": m.get("close_time"),
        })
    return pd.DataFrame(rows, columns=["ticker", "event_ticker", "player", "key", "threshold", "yes_bid",
                                       "yes_ask", "no_bid", "no_ask", "volume", "close_time"])


def fee(price: float, rate: float) -> float:
    """Taker fee per $1 contract at price (dollars)."""
    return rate * price * (1 - price)


def best_trade(p_yes: dict[int, float], quotes: pd.DataFrame, rate: float,
               min_edge: float) -> dict | None:
    """Best YES or NO buy across a player's Kalshi rungs, ranked by expected value
    per contract after fees (ROI is reported too). Ranking by ROI would always
    favour cheap longshots, which lean on the tail of the points distribution,
    the least reliable part of the model.

    p_yes maps threshold N -> our probability of N+ points. Returns None when
    no rung clears `min_edge` of expected value per contract.
    """
    best = None
    for q in quotes.itertuples():
        p = p_yes.get(q.threshold)
        if p is None:
            continue
        for side, prob, ask in (("YES", p, q.yes_ask), ("NO", 1 - p, q.no_ask)):
            if ask is None or pd.isna(ask) or not 0 < ask < 100:
                continue
            price = ask / 100
            cost = price + fee(price, rate)
            ev = prob - cost
            if ev < min_edge:
                continue
            roi = ev / cost
            if best is None or ev > best["ev"]:
                best = {"contract": f"{q.threshold}+ {side}", "ask_cents": ask, "fair_cents": round(100 * prob, 1),
                        "ev": ev, "edge_pp": round(100 * ev, 1), "roi": round(roi, 3), "ticker": q.ticker}
    return best
