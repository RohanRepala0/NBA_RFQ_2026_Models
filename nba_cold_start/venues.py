"""Venue scan: every prediction-market player-points price on a slate, checked
against the sportsbook consensus and against our model.

Two kinds of value, kept apart on purpose:
- market value: the venue sells an outcome cheaper than the multi-book
  consensus says it is worth, by EDGE_THRESHOLD after fees. No model needed,
  so this is the more trustworthy kind.
- model value: only our (ungraded) projection says it is cheap.

A price only counts if there is size behind it: for Polymarket the order book
is read and only contracts at or below the max price are counted.
Read-only throughout; nothing here places an order.
"""
from __future__ import annotations

import math
from datetime import date, datetime

import pandas as pd

from . import config
from .consensus import consensus_by_player
from .kalshi import fee as kalshi_fee
from .odds_math import p_over_normal
from .pipeline import events_on, latest_projections
from .players import name_from_player_id, name_key
from .polymarket import taker_fee
from .schedule import et_date
from .storage import Storage

MONTHS = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()


def kalshi_event_code(d: date, away: str, home: str) -> str:
    """KXNBAPTS-26OCT08BOSCLE -> '26OCT08BOSCLE'."""
    return f"{d:%y}{MONTHS[d.month - 1]}{d:%d}{away}{home}"


def _fee(venue: str, price: float, fee_bps: float | None) -> float:
    if venue == "kalshi":
        return kalshi_fee(price, config.VENUE_FEE_RATE["kalshi"])
    return taker_fee(price, fee_bps)


def max_price(p: float, venue: str, fee_bps: float | None, min_edge: float) -> float | None:
    """Largest price (dollars) that still leaves min_edge after the venue's fee."""
    best = None
    for c in range(1, 100):
        price = c / 100
        if p - price - _fee(venue, price, fee_bps) >= min_edge:
            best = price
    return best


def evaluate(quote: dict, p_cons_over: float | None, p_model_over: float | None,
             book: dict[str, list[tuple[float, float]]] | None = None,
             min_edge: float = config.EDGE_THRESHOLD) -> list[dict]:
    """Both sides of one venue market. `book` maps 'YES'/'NO' to ask levels (dollars, size)."""
    out = []
    line = quote["line"]
    for side, ask_c, p_c, p_m in (
            ("YES", quote.get("yes_ask"), p_cons_over, p_model_over),
            ("NO", quote.get("no_ask"), None if p_cons_over is None else 1 - p_cons_over,
             None if p_model_over is None else 1 - p_model_over)):
        if ask_c is None or (isinstance(ask_c, float) and math.isnan(ask_c)) or not 0 < ask_c < 100:
            continue
        price = ask_c / 100
        cost = price + _fee(quote["venue"], price, quote.get("fee_bps"))
        e_cons = None if p_c is None else p_c - cost
        e_model = None if p_m is None else p_m - cost
        market_ok = e_cons is not None and e_cons >= min_edge
        model_ok = e_model is not None and e_model >= min_edge
        verdict = ("market + model value" if market_ok and model_ok else
                   "market value" if market_ok else "model value only" if model_ok else "no edge")
        ref = p_c if market_ok or (p_m is None and p_c is not None) else p_m
        size = None
        if book and side in book and ref is not None:
            cap = max_price(ref, quote["venue"], quote.get("fee_bps"), min_edge)
            size = 0.0 if cap is None else sum(s for p, s in book[side] if p <= cap + 1e-9)
        out.append({
            "venue": quote["venue"], "player": quote["player"],
            "contract": f"{'over' if side == 'YES' else 'under'} {line:g}", "ask_cents": round(ask_c, 1),
            "fee_cents": round(100 * (cost - price), 2),
            "fair_market": None if p_c is None else round(100 * p_c, 1),
            "fair_model": None if p_m is None else round(100 * p_m, 1),
            "edge_vs_market_pp": None if e_cons is None else round(100 * e_cons, 1),
            "edge_vs_model_pp": None if e_model is None else round(100 * e_model, 1),
            "roi": None if (e_cons if market_ok else e_model) is None else round((e_cons if market_ok else e_model) / cost, 3),
            "size_at_edge": size, "verdict": verdict,
        })
    return out


def scan(storage: Storage, d: date, now: datetime, polymarket_fetch=None, kalshi_quotes: pd.DataFrame | None = None,
         book_fetch=None, min_edge: float = config.EDGE_THRESHOLD) -> pd.DataFrame:
    """`polymarket_fetch(away, home, date) -> DataFrame` and `book_fetch(token) -> asks` are
    injected so tests (and a run without network) never touch the venues."""
    rows = []
    for ev in events_on(storage, d).itertuples():
        if ev.home_abbr in config.CATALOG_EXCLUDED_TEAMS or ev.away_abbr in config.CATALOG_EXCLUDED_TEAMS:
            continue
        cons = {name_key(name_from_player_id(pid)): c
                for pid, c in consensus_by_player(storage, ev.event_id, as_of=now, before=now).items()}
        projs = {name_key(p.player_name): p for p in latest_projections(storage, ev.event_id, now).itertuples()
                 if p.mean is not None and not pd.isna(p.mean)}
        quotes = []
        if polymarket_fetch is not None:
            pm = polymarket_fetch(ev.away_abbr, ev.home_abbr, et_date(ev.starts_at))
            quotes += [] if pm is None or pm.empty else pm.to_dict("records")
        if kalshi_quotes is not None and len(kalshi_quotes):
            code = kalshi_event_code(et_date(ev.starts_at), ev.away_abbr, ev.home_abbr)
            k = kalshi_quotes[kalshi_quotes.event_ticker.str.endswith(code)]
            quotes += [{**q, "venue": "kalshi", "line": q["threshold"] - 0.5, "fee_bps": None}
                       for q in k.to_dict("records")]
        for q in quotes:
            c = cons.get(q["key"])
            p_cons = c.p_over_at(q["line"]) if c is not None and c.mean is not None and c.n_books >= config.MIN_PRICED_BOOKS else None
            pr = projs.get(q["key"])
            p_model = p_over_normal(pr.mean, q["line"], sd=pr.sd) if pr is not None else None
            book = None
            if book_fetch is not None and q["venue"] == "polymarket":
                book = {"YES": book_fetch(q["token_yes"]) if q.get("token_yes") else [],
                        "NO": book_fetch(q["token_no"]) if q.get("token_no") else []}
            for r in evaluate(q, p_cons, p_model, book, min_edge):
                rows.append({"game": f"{ev.away_abbr} @ {ev.home_abbr}", **r})
    return pd.DataFrame(rows)
