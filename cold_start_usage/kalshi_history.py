"""Kalshi's public archive of settled NBA player-prop markets, for backtesting.

Kalshi moves settled markets older than a cutoff to /historical/...: every
KXNBAPTS ladder from 2025-26 is there with its result, its settlement value
(players who never take the court settle "scalar" at a fair price), and
candlesticks with bid/ask OHLC, last-trade price, volume and open interest.

`download` copies them into a separate research DuckDB (data/history/, git-
ignored): 1-minute candles for the 24 hours before tip (markets usually open
about 16 hours ahead), one request per market, since archived markets have no
batch or event-level candle endpoint. It is resumable: markets already fetched
are skipped, so the job can be stopped and restarted. Public market-data GETs
only, no key, about one request a second, backing off 30-60 s on HTTP 429.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pandas as pd
import requests

from . import config
from .kalshi import BASE

HISTORY_DB = config.DATA_DIR / "history" / "kalshi_history.duckdb"
HEADERS = {"User-Agent": "cold-start-usage-research/1.0"}
# Regular-season KXNBAPTS markets carry occurrence_datetime = scheduled tip + 3h
# (checked on the 2026 Finals and the Oct 20 opener ladders).
TIP_BEFORE_OCCURRENCE = timedelta(hours=3)
WINDOWS = ((1, timedelta(hours=24), timedelta(0)),)        # (minutes per candle, from tip - 24h, to tip)
# Titles seen in the archive: "Tyler Herro records 30+ points" and "Victor Wembanyama: 40+ points".
TITLE_RE = re.compile(r"^(?P<name>.+?)(?::\s*|\s+records\s+)(?P<n>\d+)\+", re.I)

SCHEMA = {
    "markets": """ticker VARCHAR PRIMARY KEY, event_ticker VARCHAR, series VARCHAR, title VARCHAR,
                  player VARCHAR, team VARCHAR, player_uuid VARCHAR, threshold INTEGER, floor_strike DOUBLE,
                  strike_type VARCHAR, result VARCHAR, settlement_value DOUBLE, volume DOUBLE,
                  open_time TIMESTAMP, close_time TIMESTAMP, occurrence_time TIMESTAMP, tip_est TIMESTAMP,
                  fetched_at TIMESTAMP""",
    "candles": """ticker VARCHAR, interval_min INTEGER, end_ts TIMESTAMP,
                  yes_bid_open DOUBLE, yes_bid_high DOUBLE, yes_bid_low DOUBLE, yes_bid_close DOUBLE,
                  yes_ask_open DOUBLE, yes_ask_high DOUBLE, yes_ask_low DOUBLE, yes_ask_close DOUBLE,
                  price_open DOUBLE, price_high DOUBLE, price_low DOUBLE, price_close DOUBLE, price_mean DOUBLE,
                  volume DOUBLE, open_interest DOUBLE""",
    "progress": "ticker VARCHAR, interval_min INTEGER, n_candles INTEGER, fetched_at TIMESTAMP",
}


@dataclass
class Throttle:
    """At most one request per `interval` seconds."""
    interval: float = 1.05
    _last: float = 0.0

    def wait(self) -> None:
        gap = time.monotonic() - self._last
        if gap < self.interval:
            time.sleep(self.interval - gap)
        self._last = time.monotonic()


def _num(x) -> float | None:
    if x in (None, ""):
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _ts(x) -> datetime | None:
    if not x:
        return None
    return pd.Timestamp(x).tz_convert("UTC").tz_localize(None).to_pydatetime()


class KalshiArchive:
    """Throttled reader for /historical/... (no key)."""

    def __init__(self, session: requests.Session | None = None, throttle: Throttle | None = None,
                 max_retries: int = 6):
        self.session = session or requests.Session()
        self.throttle = throttle or Throttle()
        self.max_retries = max_retries

    def get(self, path: str, params: dict | None = None) -> dict:
        for attempt in range(self.max_retries):
            self.throttle.wait()
            try:
                resp = self.session.get(f"{BASE}{path}", params=params, headers=HEADERS, timeout=30)
            except requests.RequestException:          # proxy drops and timeouts: wait and retry
                time.sleep(min(120, 30 * (attempt + 1)))
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                time.sleep(min(120, 30 * (attempt + 1)))  # no Retry-After header is sent
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError(f"Kalshi {path}: still failing after {self.max_retries} retries")

    def markets(self, series: str) -> list[dict]:
        out, cursor = [], None
        while True:
            params = {"series_ticker": series, "limit": 1000}
            if cursor:
                params["cursor"] = cursor
            body = self.get("/historical/markets", params)
            page = body.get("markets") or []
            out += page
            cursor = body.get("cursor")
            if not cursor or not page:
                return out

    def candles(self, ticker: str, start: datetime, end: datetime, interval_min: int) -> list[dict]:
        params = {"start_ts": int(start.replace(tzinfo=timezone.utc).timestamp()),
                  "end_ts": int(end.replace(tzinfo=timezone.utc).timestamp()),
                  "period_interval": interval_min}
        return self.get(f"/historical/markets/{ticker}/candlesticks", params).get("candlesticks") or []


def market_row(m: dict, fetched_at: datetime) -> dict:
    """One archive market -> one row. The team comes from the ticker's player segment
    (KXNBAPTS-26JUN13NYKSAS-SASVWEMBANYAMA1-30 -> SAS), checked against the event's two teams."""
    parts = (m.get("ticker") or "").split("-")
    event_code = parts[1] if len(parts) > 1 else ""
    teams = (event_code[-6:-3], event_code[-3:]) if len(event_code) >= 6 else ("", "")
    seg = parts[2] if len(parts) > 2 else ""
    team = next((t for t in teams if t and seg.startswith(t)), None)
    title = m.get("title") or ""
    hit = TITLE_RE.match(title.strip())
    player = hit["name"].strip() if hit else None
    floor = _num(m.get("floor_strike"))
    occ = _ts(m.get("occurrence_datetime") or m.get("expected_expiration_time"))
    return {
        "ticker": m.get("ticker"), "event_ticker": m.get("event_ticker"), "series": parts[0] if parts else None,
        "title": title, "player": player, "team": team,
        "player_uuid": (m.get("custom_strike") or {}).get("basketball_player"),
        "threshold": None if floor is None else int(round(floor + 0.5)), "floor_strike": floor,
        "strike_type": m.get("strike_type"), "result": m.get("result"),
        "settlement_value": _num(m.get("settlement_value_dollars")), "volume": _num(m.get("volume_fp")),
        "open_time": _ts(m.get("open_time")), "close_time": _ts(m.get("close_time")),
        "occurrence_time": occ, "tip_est": None if occ is None else occ - TIP_BEFORE_OCCURRENCE,
        "fetched_at": fetched_at,
    }


def candle_rows(ticker: str, interval_min: int, candles: list[dict]) -> list[dict]:
    rows = []
    for c in candles:
        bid, ask, price = c.get("yes_bid") or {}, c.get("yes_ask") or {}, c.get("price") or {}
        rows.append({
            "ticker": ticker, "interval_min": interval_min,
            "end_ts": datetime.fromtimestamp(int(c["end_period_ts"]), timezone.utc).replace(tzinfo=None),
            **{f"yes_bid_{k}": _num(bid.get(k)) for k in ("open", "high", "low", "close")},
            **{f"yes_ask_{k}": _num(ask.get(k)) for k in ("open", "high", "low", "close")},
            **{f"price_{k}": _num(price.get(k)) for k in ("open", "high", "low", "close", "mean")},
            "volume": _num(c.get("volume")), "open_interest": _num(c.get("open_interest")),
        })
    return rows


class HistoryStore:
    """The research cache. Separate from the append-only decision log on purpose:
    it holds the venue's own archive, which can be re-downloaded at any time."""

    def __init__(self, path: Path | str | None = None):
        path = Path(path or HISTORY_DB)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(str(path))
        for table, ddl in SCHEMA.items():
            self.con.execute(f"CREATE TABLE IF NOT EXISTS {table} ({ddl})")

    def upsert_markets(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        df = pd.DataFrame(rows)
        self.con.register("incoming", df)
        self.con.execute("DELETE FROM markets WHERE ticker IN (SELECT ticker FROM incoming)")
        self.con.execute(f"INSERT INTO markets SELECT {', '.join(df.columns)} FROM incoming")
        self.con.unregister("incoming")
        return len(df)

    def add_candles(self, ticker: str, interval_min: int, rows: list[dict], fetched_at: datetime) -> None:
        if rows:
            df = pd.DataFrame(rows)
            self.con.register("incoming", df)
            self.con.execute(f"INSERT INTO candles SELECT {', '.join(df.columns)} FROM incoming")
            self.con.unregister("incoming")
        self.con.execute("INSERT INTO progress VALUES (?, ?, ?, ?)", [ticker, interval_min, len(rows), fetched_at])

    def done(self) -> set[tuple[str, int]]:
        return {(t, int(i)) for t, i in self.con.execute("SELECT ticker, interval_min FROM progress").fetchall()}

    def query(self, sql: str, params: list | None = None) -> pd.DataFrame:
        return self.con.execute(sql, params or []).df()

    def close(self) -> None:
        self.con.close()


def download(series: str = "KXNBAPTS", store: HistoryStore | None = None, archive: KalshiArchive | None = None,
             limit: int | None = None, refresh_markets: bool = True, log=print) -> dict:
    """Fetch the series' archive markets, then candles for each one not yet stored,
    oldest game first. Returns counts; safe to interrupt and re-run."""
    store = store or HistoryStore()
    archive = archive or KalshiArchive()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if refresh_markets or store.query("SELECT count(*) n FROM markets WHERE series = ?", [series]).n.iloc[0] == 0:
        rows = [market_row(m, now) for m in archive.markets(series)]
        store.upsert_markets(rows)
        log(f"{series}: {len(rows)} archive markets")
    markets = store.query("""SELECT ticker, open_time, tip_est FROM markets
                             WHERE series = ? AND tip_est IS NOT NULL ORDER BY tip_est, ticker""", [series])
    done = store.done()
    todo = [m for m in markets.itertuples() if any((m.ticker, w[0]) not in done for w in WINDOWS)]
    if limit is not None:
        todo = todo[:limit]
    log(f"{len(todo)} of {len(markets)} markets still need candles")
    fetched = 0
    for i, m in enumerate(todo, 1):
        tip = pd.Timestamp(m.tip_est).to_pydatetime()
        opened = pd.Timestamp(m.open_time).to_pydatetime() if m.open_time is not None and not pd.isna(m.open_time) else None
        for interval, lead, lag in WINDOWS:
            if (m.ticker, interval) in done:
                continue
            start, end = tip - lead, tip - lag
            if opened is not None:
                start = max(start, opened)
            rows = [] if start >= end else candle_rows(m.ticker, interval, archive.candles(m.ticker, start, end, interval))
            store.add_candles(m.ticker, interval, rows, datetime.now(timezone.utc).replace(tzinfo=None))
            fetched += 1
        if i % 200 == 0:
            log(f"  {i}/{len(todo)} markets ({m.ticker})")
    return {"markets": len(markets), "fetched_requests": fetched,
            "complete": len(markets) - len(todo) + (len(todo) if limit is None else min(limit, len(todo)))}
