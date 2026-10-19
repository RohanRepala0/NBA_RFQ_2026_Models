"""DuckDB storage. Append-only by construction.

The Storage class exposes `append` and read-only `query` only: there is no
update or delete path, so a logged projection or signal can never be rewritten
after the fact (hard rule 6). Every append is also checked against the book
allowlist (hard rule 1) and refused if an off-list book appears.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

import duckdb
import pandas as pd

from .config import DB_PATH, VENUES, is_allowed_book

SCHEMA: dict[str, dict[str, str]] = {
    "api_calls": {
        "ts": "TIMESTAMP", "endpoint": "VARCHAR", "params": "VARCHAR",
        "http_status": "INTEGER", "objects": "INTEGER", "note": "VARCHAR",
    },
    "events": {
        "ts": "TIMESTAMP", "event_id": "VARCHAR", "starts_at": "TIMESTAMP",
        "home_team_id": "VARCHAR", "away_team_id": "VARCHAR",
        "home_abbr": "VARCHAR", "away_abbr": "VARCHAR",
        "cancelled": "BOOLEAN", "started": "BOOLEAN", "finalized": "BOOLEAN",
        "snapshot_tag": "VARCHAR",
    },
    "event_players": {
        "ts": "TIMESTAMP", "event_id": "VARCHAR", "player_id": "VARCHAR",
        "team_id": "VARCHAR", "team_abbr": "VARCHAR", "name": "VARCHAR",
        "status": "VARCHAR",
    },
    "odds_snapshots": {
        "ts": "TIMESTAMP", "event_id": "VARCHAR", "odd_id": "VARCHAR",
        "player_id": "VARCHAR", "side": "VARCHAR", "book": "VARCHAR",
        "book_role": "VARCHAR", "line": "DOUBLE", "odds_american": "DOUBLE", "available": "BOOLEAN",
        "is_main_line": "BOOLEAN", "quote_ts": "TIMESTAMP", "snapshot_tag": "VARCHAR",
    },
    "books_seen": {
        "ts": "TIMESTAMP", "event_id": "VARCHAR", "book": "VARCHAR",
        "book_role": "VARCHAR", "posts_player_points": "BOOLEAN",
    },
    "projections": {
        "ts": "TIMESTAMP", "event_id": "VARCHAR", "player_id": "VARCHAR",
        "player_name": "VARCHAR", "team": "VARCHAR", "new_team": "BOOLEAN",
        "scenario": "VARCHAR", "mean": "DOUBLE", "sd": "DOUBLE",
        "proj_mpg": "DOUBLE", "usg_proj": "DOUBLE",
        "inputs_hash": "VARCHAR", "model_version": "VARCHAR",
    },
    "signals": {
        "ts": "TIMESTAMP", "event_id": "VARCHAR", "player_id": "VARCHAR",
        "player_name": "VARCHAR", "team": "VARCHAR", "new_team": "BOOLEAN",
        "timing": "VARCHAR", "side": "VARCHAR", "model_p": "DOUBLE",
        "consensus_p": "DOUBLE", "line": "DOUBLE", "edge": "DOUBLE",
        "decision": "VARCHAR", "reason": "VARCHAR",
        "model_mean": "DOUBLE", "consensus_mean": "DOUBLE", "n_books": "INTEGER",
        "books": "VARCHAR", "snapshot_ts": "TIMESTAMP", "projection_ts": "TIMESTAMP",
        "model_version": "VARCHAR",
    },
    # Prediction-market prices read from the venues' own public APIs (dollars).
    "venue_snapshots": {
        "ts": "TIMESTAMP", "tag": "VARCHAR", "venue": "VARCHAR", "event_id": "VARCHAR",
        "event_ticker": "VARCHAR", "ticker": "VARCHAR", "player": "VARCHAR", "player_id": "VARCHAR",
        "team": "VARCHAR", "threshold": "INTEGER", "line": "DOUBLE",
        "yes_bid": "DOUBLE", "yes_ask": "DOUBLE", "no_bid": "DOUBLE", "no_ask": "DOUBLE",
        "yes_ask_size": "DOUBLE", "no_ask_size": "DOUBLE", "volume": "DOUBLE", "open_interest": "DOUBLE",
        "fee_rate": "DOUBLE", "tip_ts": "TIMESTAMP", "parse_error": "VARCHAR",
    },
    # One row per venue contract and side, from decision.evaluate_contract: the only
    # place a contract can be called actionable.
    "venue_signals": {
        "ts": "TIMESTAMP", "signal_id": "VARCHAR", "tag": "VARCHAR", "event_id": "VARCHAR",
        "game": "VARCHAR", "player_id": "VARCHAR", "player": "VARCHAR", "team": "VARCHAR",
        "venue": "VARCHAR", "ticker": "VARCHAR", "event_ticker": "VARCHAR", "contract": "VARCHAR",
        "side": "VARCHAR", "threshold": "INTEGER", "line": "DOUBLE", "rung_distance": "DOUBLE",
        "quote_ts": "TIMESTAMP", "tip_ts": "TIMESTAMP", "status": "VARCHAR",
        "bid": "DOUBLE", "ask": "DOUBLE", "ask_size": "DOUBLE", "max_price": "DOUBLE",
        "size_at_edge": "DOUBLE", "cost": "DOUBLE", "fee_rate": "DOUBLE",
        "consensus_ts": "TIMESTAMP", "consensus_mean": "DOUBLE", "consensus_line": "DOUBLE",
        "n_books": "INTEGER", "p_market": "DOUBLE", "model_mean": "DOUBLE", "projection_ts": "TIMESTAMP",
        "w_model": "DOUBLE", "blend_mean": "DOUBLE", "p_blend": "DOUBLE", "p_spread": "DOUBLE",
        "ev_market": "DOUBLE", "ev_blend": "DOUBLE", "tau": "DOUBLE",
        "kelly": "DOUBLE", "stake_frac": "DOUBLE", "contracts": "DOUBLE", "stake_usd": "DOUBLE",
        "decision": "VARCHAR", "reason": "VARCHAR", "model_version": "VARCHAR", "config_hash": "VARCHAR",
    },
    # Fills Rohan entered by hand on a venue (never placed by this code).
    "tickets": {
        "ts": "TIMESTAMP", "filled_at": "TIMESTAMP", "venue": "VARCHAR", "ticker": "VARCHAR",
        "side": "VARCHAR", "contracts": "DOUBLE", "price": "DOUBLE", "fees": "DOUBLE",
        "signal_id": "VARCHAR", "note": "VARCHAR",
    },
    # Venue settlements: 1 / 0, or a fair price for a player who never took the court.
    "venue_settlements": {
        "ts": "TIMESTAMP", "venue": "VARCHAR", "ticker": "VARCHAR", "result": "VARCHAR",
        "settlement_value": "DOUBLE", "settled_ts": "TIMESTAMP",
    },
    "results": {
        "ts": "TIMESTAMP", "event_id": "VARCHAR", "player_id": "VARCHAR",
        "actual_points": "DOUBLE", "close_consensus_line": "DOUBLE",
        "close_consensus_p": "DOUBLE", "close_consensus_mean": "DOUBLE",
        "close_n_books": "INTEGER", "close_snapshot_ts": "TIMESTAMP",
        "close_source": "VARCHAR",
    },
}

_READ_ONLY = re.compile(r"^\s*(select|with|describe|show|pragma\s+table_info)\b", re.I)


class OffListBookError(RuntimeError):
    """A bookmakerID that is not on the allowlist tried to reach storage."""


class AfterTipError(RuntimeError):
    """A venue price or decision stamped at or after tip (log before outcome)."""


PRE_TIP_TABLES = {"venue_snapshots": "ts", "venue_signals": "quote_ts"}


BOOK_COLUMNS = ("book",)          # one bookmakerID per row
BOOK_LIST_COLUMNS = ("books",)    # comma-separated bookmakerIDs


def utcnow() -> datetime:
    """Naive UTC: every TIMESTAMP column in this database is UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_naive_utc(ts) -> datetime | None:
    if ts is None or (isinstance(ts, float) and pd.isna(ts)):
        return None
    t = pd.Timestamp(ts)
    if pd.isna(t):
        return None
    if t.tzinfo is not None:
        t = t.tz_convert("UTC").tz_localize(None)
    return t.to_pydatetime()


def assert_allowed_venues(df: pd.DataFrame, table: str) -> None:
    if "venue" in df.columns:
        bad = df.venue.dropna().astype(str).map(lambda v: v not in VENUES)
        if bad.any():
            raise OffListBookError(f"{table}.venue: {int(bad.sum())} value(s) not in {VENUES}")


def assert_pre_tip(df: pd.DataFrame, table: str) -> None:
    col = PRE_TIP_TABLES.get(table)
    if col is None or "tip_ts" not in df.columns or col not in df.columns:
        return
    t = pd.to_datetime(df[col]); tip = pd.to_datetime(df.tip_ts)
    late = (t.notna() & tip.notna() & (t >= tip))
    if late.any():
        raise AfterTipError(f"{table}: {int(late.sum())} row(s) stamped at or after tip")


def assert_allowed_books(df: pd.DataFrame, table: str) -> None:
    for col in BOOK_COLUMNS + BOOK_LIST_COLUMNS:
        if col not in df.columns:
            continue
        values = df[col].dropna().astype(str)
        if col in BOOK_LIST_COLUMNS:
            values = values.str.split(",").explode().str.strip()
            values = values[values != ""]
        bad = values.map(lambda v: not is_allowed_book(v))
        if bad.any():
            raise OffListBookError(f"{table}.{col}: {int(bad.sum())} value(s) not on the book allowlist")


class Storage:
    def __init__(self, path: Path | str = DB_PATH):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._con = duckdb.connect(str(path))
        for table, cols in SCHEMA.items():
            ddl = ", ".join(f"{c} {t}" for c, t in cols.items())
            self._con.execute(f"CREATE TABLE IF NOT EXISTS {table} ({ddl})")
            # Additive migration only: a column added to SCHEMA is added to an
            # existing table; nothing is ever dropped or rewritten.
            have = {r[0] for r in self._con.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = ?", [table]).fetchall()}
            for c, t in cols.items():
                if c not in have:
                    self._con.execute(f"ALTER TABLE {table} ADD COLUMN {c} {t}")

    def close(self) -> None:
        self._con.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def append(self, table: str, rows: pd.DataFrame | Iterable[Mapping]) -> int:
        if table not in SCHEMA:
            raise KeyError(f"Unknown table {table}")
        df = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(list(rows))
        if df.empty:
            return 0
        unknown = set(df.columns) - set(SCHEMA[table])
        if unknown:
            raise ValueError(f"{table}: unknown columns {sorted(unknown)}")
        if "ts" not in df.columns:
            df["ts"] = utcnow()
        assert_allowed_books(df, table)
        assert_allowed_venues(df, table)
        assert_pre_tip(df, table)
        for col, typ in SCHEMA[table].items():
            if col not in df.columns:
                df[col] = None
            if typ == "TIMESTAMP":
                df[col] = pd.Series([to_naive_utc(v) for v in df[col]], index=df.index, dtype="datetime64[us]")
            elif typ in ("VARCHAR",):
                df[col] = df[col].astype(object).where(df[col].notna(), None)
        cols = list(SCHEMA[table])
        df = df[cols]
        self._con.register("_incoming", df)
        try:
            self._con.execute(f"INSERT INTO {table} ({', '.join(cols)}) SELECT {', '.join(cols)} FROM _incoming")
        finally:
            self._con.unregister("_incoming")
        return len(df)

    def query(self, sql: str, params: list | None = None) -> pd.DataFrame:
        if not _READ_ONLY.match(sql) or ";" in sql.strip().rstrip(";"):
            raise PermissionError("Storage.query is read-only (single SELECT/WITH statement)")
        return self._con.execute(sql, params or []).df()

    def count(self, table: str) -> int:
        if table not in SCHEMA:
            raise KeyError(table)
        return int(self._con.execute(f"SELECT count(*) FROM {table}").fetchone()[0])

    # --- convenience reads -------------------------------------------------------
    def objects_used_this_month(self, now: datetime | None = None) -> int:
        now = now or utcnow()
        start = datetime(now.year, now.month, 1)
        row = self._con.execute(
            "SELECT coalesce(sum(objects), 0) FROM api_calls WHERE ts >= ?", [start]).fetchone()
        return int(row[0])

    def latest_events(self) -> pd.DataFrame:
        return self.query("""
            SELECT * EXCLUDE (rn) FROM (
              SELECT *, row_number() OVER (PARTITION BY event_id ORDER BY ts DESC) AS rn FROM events)
            WHERE rn = 1""")
