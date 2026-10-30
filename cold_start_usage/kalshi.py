"""Read-only Kalshi market data for NBA player props: points, rebounds and assists, and the
shadow stats (threes, steals, blocks, points + rebounds + assists: config.KALSHI_SERIES).

Kalshi lists each stat as its own series (config.KALSHI_SERIES: KXNBAPTS,
KXNBAREB, KXNBAAST) of "N+" ladders, one binary market per rung (points 10+,
15+, ... in steps of 5; rebounds and assists in steps of 1-2), grouped into one
event per game: KXNBAPTS-26OCT20BOSDET is Celtics at Pistons (away then home,
ET date), and KXNBAPTS-26OCT20BOSDET-BOSDWHITE9-25 is "Derrick White: 25+
points" with floor_strike 24.5. YES pays $1 if the player's total is more than
floor_strike. The stat comes from the series prefix of the event ticker and must
match the title's stat word ("Victor Wembanyama: 8+ rebounds"); a mismatch or an
unknown series is a parse error, never a guess.

Facts this module relies on (checked against the live API):
- Prices are dollar strings (yes_ask_dollars ...); the old integer-cent fields
  and `volume` are gone (volume_fp, open_interest_fp, *_size_fp instead).
- The order book returns bids only. The YES ask is 1 - the best NO bid, with
  that bid's size; the NO ask is 1 - the best YES bid.
- Markets stay open in-game (close_time = tip + 48h, can_close_early), so the
  tip must come from the schedule, never from close_time. occurrence_datetime
  is the scheduled tip + 3h.
- A player who never takes the court settles "scalar" at a fair price, not NO.
- Unauthenticated reads get HTTP 429 (no Retry-After) after short bursts, and
  sometimes at one call every few seconds: read at most one call a second, back
  off 30 s and more on a 429, and read order books in batches of up to 100
  (GET /markets/orderbooks?tickers=...).

Public market-data GETs only: no account, no key, and no portfolio or order
endpoint is ever called (hard rule 4). Positions are entered by hand.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
import requests

from . import config
from .players import name_key

BASE = "https://api.elections.kalshi.com/trade-api/v2"
SERIES = "KXNBAPTS"                                # points: the archive and the backtest use this one
SERIES_STAT = {series: stat for stat, series in config.KALSHI_SERIES.items()}
HEADERS = {"User-Agent": "cold-start-usage-research/1.0"}
# "Derrick White: 25+ points" (live), "Tyler Herro records 30+ points" (archive), "Derrick White: 25+" (sub-title)
TITLE_RE = re.compile(r"^(?P<name>.+?)(?::\s*|\s+records\s+)(?P<n>\d+)\+(?:\s+(?P<word>[a-z][a-z, -]*[a-z]))?", re.I)
# A title's stat words per stat ("Damian Lillard: 6+ threes", "... 35+ points, rebounds, and assists").
STAT_WORDS = {"threes": ("three", "threes", "3-pointer", "3-pointers"),
              "pra": ("points, rebounds, and assists", "points, rebounds and assists", "pts+reb+ast")}
MONTHS = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()
TIP_BEFORE_OCCURRENCE = timedelta(hours=3)
COLUMNS = ["ticker", "event_ticker", "stat", "player", "key", "team", "threshold", "line", "strike_type",
           "yes_bid", "yes_ask", "no_bid", "no_ask", "yes_bid_size", "yes_ask_size", "no_ask_size",
           "volume", "open_interest", "status", "close_time", "tip_est", "parse_error"]


@dataclass
class Throttle:
    """At most one request per `interval` seconds (unauthenticated reads are rate limited)."""
    interval: float = 1.0
    _last: float = 0.0

    def wait(self) -> None:
        gap = time.monotonic() - self._last
        if gap < self.interval:
            time.sleep(self.interval - gap)
        self._last = time.monotonic()


class KalshiReader:
    def __init__(self, session: requests.Session | None = None, throttle: Throttle | None = None,
                 max_retries: int = 3):
        self.session = session or requests.Session()
        self.throttle = throttle or Throttle()
        self.max_retries = max_retries

    def get(self, path: str, params: dict | None = None) -> dict:
        for attempt in range(self.max_retries):
            self.throttle.wait()
            last = attempt == self.max_retries - 1
            try:
                resp = self.session.get(f"{BASE}{path}", params=params, headers=HEADERS, timeout=20)
            except requests.RequestException:          # proxy drops and timeouts: wait and retry
                if not last:
                    time.sleep(30 * (attempt + 1))
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                if not last:
                    time.sleep(30 * (attempt + 1))   # live reads give up after ~90 s, not minutes
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError(f"Kalshi {path}: rate limited after {self.max_retries} retries")

    def open_markets(self, series: str = SERIES, event_ticker: str | None = None,
                     max_pages: int = 20) -> list[dict]:
        out, cursor = [], None
        for _ in range(max_pages):
            params = {"series_ticker": series, "status": "open", "limit": 1000}
            if event_ticker:
                params["event_ticker"] = event_ticker
            if cursor:
                params["cursor"] = cursor
            body = self.get("/markets", params)
            out += body.get("markets") or []
            cursor = body.get("cursor")
            if not cursor or not body.get("markets"):
                return out
        raise RuntimeError(f"Kalshi {series}: more than {max_pages} pages; refusing a truncated market list")

    def market(self, ticker: str) -> dict:
        return self.get(f"/markets/{ticker}").get("market") or {}

    def orderbook(self, ticker: str) -> dict[str, list[tuple[float, float]]]:
        return asks_from_orderbook(self.get(f"/markets/{ticker}/orderbook"))

    def orderbooks(self, tickers: list[str]) -> dict[str, dict[str, list[tuple[float, float]]]]:
        """Ask ladders for many markets, 100 per call."""
        out = {}
        tickers = list(dict.fromkeys(tickers))
        for i in range(0, len(tickers), 100):
            chunk = tickers[i:i + 100]
            body = self.get("/markets/orderbooks", [("tickers", t) for t in chunk])
            books = body.get("orderbooks") or []
            for t, b in zip(chunk, books):
                out[b.get("ticker") or t] = asks_from_orderbook(b)
        return out


def fetch_open_markets(series: str = SERIES, session: requests.Session | None = None,
                       max_pages: int = 20) -> list[dict]:
    return KalshiReader(session).open_markets(series, max_pages=max_pages)


def event_code(d: date, away: str, home: str) -> str:
    """KXNBAPTS-26OCT20BOSDET -> '26OCT20BOSDET' (ET date, away team first)."""
    return f"{d:%y}{MONTHS[d.month - 1]}{d:%d}{away}{home}"


def _num(x) -> float | None:
    if x in (None, ""):
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _ts(x):
    return None if not x else pd.Timestamp(x).tz_convert("UTC").tz_localize(None)


def stat_from_ticker(ticker: str | None) -> str | None:
    """KXNBAREB-26OCT20OKCSAS(-...) -> 'rebounds'; None for a series not in config.KALSHI_SERIES."""
    return SERIES_STAT.get((ticker or "").split("-")[0])


def stat_word_ok(word: str | None, stat: str) -> bool:
    """A title's stat words ('rebounds', 'rebound', 'points, rebounds, and assists') against the
    series' stat. No word (a sub-title such as 'Derrick White: 25+') leaves the series to decide."""
    if word is None:
        return True
    w = " ".join(word.lower().split())
    if any(w in words for s, words in STAT_WORDS.items() if s != stat):   # another stat's own words
        return False
    first = w.split(" ")[0].rstrip(",")                                  # "points" in "points in the game"
    return w in STAT_WORDS.get(stat, ()) or first.rstrip("s") == stat.rstrip("s") or first in STAT_WORDS.get(stat, ())


def team_from_ticker(ticker: str) -> str | None:
    """KXNBAPTS-26OCT20BOSDET-BOSDWHITE9-25 -> 'BOS' (must be one of the event's two teams)."""
    parts = (ticker or "").split("-")
    if len(parts) < 3 or len(parts[1]) < 6:
        return None
    away, home = parts[1][-6:-3], parts[1][-3:]
    return next((t for t in (away, home) if parts[2].startswith(t)), None)


def parse_markets(markets: list[dict]) -> pd.DataFrame:
    """One row per market, with its stat from the series. Rows that can't be parsed are kept with
    `parse_error` set, so a format change shows up in the log instead of silently emptying the board."""
    rows = []
    for m in markets:
        title = (m.get("title") or m.get("yes_sub_title") or "").strip()
        hit = TITLE_RE.match(title)
        floor = _num(m.get("floor_strike"))
        threshold = None if floor is None else int(round(floor + 0.5))
        series = (m.get("event_ticker") or m.get("ticker") or "").split("-")[0]
        stat = stat_from_ticker(series)
        error = None
        if floor is None or abs(floor + 0.5 - round(floor + 0.5)) > 1e-9:
            error = f"no half-point floor_strike ({m.get('floor_strike')})"
        elif m.get("strike_type") not in ("greater", "structured"):
            error = f"strike_type {m.get('strike_type')!r}"
        elif stat is None:
            error = f"unknown series {series!r}"
        elif not hit:
            error = f"unparsed title {title!r}"
        elif int(hit["n"]) != threshold:
            error = f"title says {hit['n']}+ but floor_strike is {floor}"
        elif not stat_word_ok(hit["word"], stat):
            error = f"title says {hit['word']!r} but {series} is {stat}"
        occ = _ts(m.get("occurrence_datetime") or m.get("expected_expiration_time"))
        player = hit["name"].strip() if hit else None
        rows.append({
            "ticker": m.get("ticker"), "event_ticker": m.get("event_ticker"), "stat": stat,
            "player": player, "key": name_key(player) if player else None,
            "team": team_from_ticker(m.get("ticker")), "threshold": threshold,
            "line": floor, "strike_type": m.get("strike_type"),
            "yes_bid": _num(m.get("yes_bid_dollars")), "yes_ask": _num(m.get("yes_ask_dollars")),
            "no_bid": _num(m.get("no_bid_dollars")), "no_ask": _num(m.get("no_ask_dollars")),
            "yes_bid_size": _num(m.get("yes_bid_size_fp")), "yes_ask_size": _num(m.get("yes_ask_size_fp")),
            # NO ask = 1 - best YES bid, so its size is the YES bid size
            "no_ask_size": _num(m.get("yes_bid_size_fp")),
            "volume": _num(m.get("volume_fp")), "open_interest": _num(m.get("open_interest_fp")),
            "status": m.get("status"), "close_time": _ts(m.get("close_time")),
            "tip_est": None if occ is None else occ - TIP_BEFORE_OCCURRENCE,
            "parse_error": error,
        })
    return pd.DataFrame(rows, columns=COLUMNS)


def asks_from_orderbook(body: dict) -> dict[str, list[tuple[float, float]]]:
    """GET /markets/{ticker}/orderbook -> ask ladders, cheapest first, in dollars.

    The book holds bids only (ascending, best last): a NO bid at p is a YES offer at 1 - p."""
    book = body.get("orderbook_fp") or {}
    def ladder(bids):
        levels = [(round(1 - float(p), 4), float(s)) for p, s in bids or [] if float(s) > 0]
        return sorted(levels, key=lambda x: x[0])
    return {"YES": ladder(book.get("no_dollars")), "NO": ladder(book.get("yes_dollars"))}
