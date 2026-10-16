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

from .config import DB_PATH, is_allowed_book

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
    "venue_quotes": {
        "ts": "TIMESTAMP", "venue": "VARCHAR", "ticker": "VARCHAR", "event_ticker": "VARCHAR",
        "player": "VARCHAR", "threshold": "INTEGER", "yes_bid": "DOUBLE", "yes_ask": "DOUBLE",
        "no_bid": "DOUBLE", "no_ask": "DOUBLE", "close_time": "TIMESTAMP",
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
