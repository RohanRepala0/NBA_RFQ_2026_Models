"""Venue operations: grading at the venue's price, storage guards, the cron venue step,
the archive loader, and a static check that no code path can place an order."""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from cold_start_usage import cli
from cold_start_usage.grade import fetch_venue_settlements, fills_graded, venue_graded, venue_summary
from cold_start_usage.kalshi_history import HistoryStore, candle_rows, download, market_row
from cold_start_usage.pipeline import run_projections, snapshot_from_file
from cold_start_usage.storage import OffListBookError, Storage
from cold_start_usage.venues import Fetchers, scan
from tests.fixtures.synthetic import FETCHED, TIP, events_response, synthetic_event
from tests.test_venues import kalshi_market

DAY = TIP.date()
PACKAGE = Path(__file__).resolve().parents[1] / "cold_start_usage"


def _actionable_slate(storage):
    snapshot_from_file(storage, events_response([synthetic_event()]), FETCHED)
    run_projections(storage, DAY, FETCHED, {})
    m = kalshi_market("MIAGANTETOKOUNMPO34", "Giannis Antetokounmpo", 30, 0.38, 0.40, 50, 50)
    df = scan(storage, DAY, FETCHED + timedelta(minutes=1), Fetchers(kalshi_markets=lambda: [m]), tag="t-60m")
    return m["ticker"], df


def test_paper_pnl_uses_the_venue_settlement_including_fair_price(storage):
    ticker, df = _actionable_slate(storage)
    act = df[df.decision == "actionable"].iloc[0]
    fetch_venue_settlements(storage, DAY, DAY, TIP + timedelta(hours=4),
                            kalshi_market=lambda t: {"status": "finalized", "result": "yes"})
    g = venue_graded(storage, DAY, DAY)
    assert len(g) == 1 and g.value.iloc[0] == 1.0
    assert g.pnl_per_contract.iloc[0] == pytest.approx(1.0 - act.cost)
    # A second settlement fetch stores nothing new; a fair-price settlement pays its value.
    assert fetch_venue_settlements(storage, DAY, DAY, TIP, kalshi_market=lambda t: {}) == 0
    s = Storage(":memory:")
    _actionable_slate(s)
    fetch_venue_settlements(s, DAY, DAY, TIP + timedelta(hours=4), kalshi_market=lambda t: {
        "status": "finalized", "result": "scalar", "settlement_value_dollars": "0.3900"})
    g2 = venue_graded(s, DAY, DAY)
    assert g2.value.iloc[0] == pytest.approx(0.39) and g2.result.iloc[0] == "scalar"
    assert venue_summary(g2)["fair_price_settlements"] == 1


def test_fills_are_graded_at_the_price_paid(storage, capsys):
    ticker, df = _actionable_slate(storage)
    sid = df[df.decision == "actionable"].signal_id.iloc[0]
    args = cli.build_parser().parse_args(["fill", "--signal-id", sid, "--contracts", "10", "--price", "0.40"])
    assert cli.cmd_fill(args, storage, lambda: FETCHED + timedelta(minutes=5)) == 0
    assert "fees $0.17" in capsys.readouterr().out                 # ceil(0.07 x 10 x 0.4 x 0.6) to the cent
    storage.append("venue_settlements", [{"venue": "kalshi", "ticker": ticker, "result": "no", "settlement_value": 0.0}])
    f = fills_graded(storage)
    assert f.pnl.iloc[0] == pytest.approx(-4.17)


def test_tickets_list_only_actionable_pre_tip(storage, capsys):
    _actionable_slate(storage)
    args = cli.build_parser().parse_args(["tickets", "--date", DAY.isoformat()])
    assert cli.cmd_tickets(args, storage, lambda: FETCHED + timedelta(minutes=2)) == 0
    out = capsys.readouterr().out
    assert "30+ YES" in out and "Giannis Antetokounmpo" in out
    assert cli.cmd_tickets(args, storage, lambda: TIP + timedelta(minutes=1)) == 0
    assert "No actionable venue contracts" in capsys.readouterr().out


def test_venue_tables_refuse_unknown_venues_and_migrate_additively(tmp_path):
    s = Storage(":memory:")
    with pytest.raises(OffListBookError):
        s.append("venue_snapshots", [{"venue": "novig", "tip_ts": TIP, "ts": FETCHED}])
    path = tmp_path / "old.duckdb"
    import duckdb
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE tickets (ts TIMESTAMP, venue VARCHAR)")      # an older, narrower table
    con.execute("INSERT INTO tickets VALUES ('2026-10-21 20:00:00', 'kalshi')")
    con.close()
    with Storage(path) as s2:
        assert s2.count("tickets") == 1                                    # kept
        assert "signal_id" in s2.query("SELECT * FROM tickets").columns   # column added


def test_cron_venue_step_runs_even_when_sportsbook_step_fails(storage, monkeypatch, capsys):
    snapshot_from_file(storage, events_response([synthetic_event()]), FETCHED)
    m = kalshi_market("MIAGANTETOKOUNMPO34", "Giannis Antetokounmpo", 30, 0.38, 0.40, 50, 50)
    monkeypatch.setattr("cold_start_usage.venues.live_fetchers", lambda: Fetchers(kalshi_markets=lambda: [m]))

    def no_key(*a, **k):
        from cold_start_usage.sgo_client import MissingAPIKey
        raise MissingAPIKey("no key")
    monkeypatch.setattr(cli, "_client", no_key)
    now = TIP - timedelta(minutes=58)
    args = cli.build_parser().parse_args(["snapshot", "--due", "--with-venues", "--with-projections"])
    assert cli.cmd_snapshot(args, storage, lambda: now) == 0
    out = capsys.readouterr().out
    assert "SportsGameOdds step skipped" in out and "Auto-projected 1 game" in out
    assert "Venues (t-60m)" in out
    assert set(storage.query("SELECT DISTINCT tag FROM venue_snapshots").tag) == {"t-60m"}
    assert cli.cmd_snapshot(args, storage, lambda: now + timedelta(minutes=2)) == 0   # taken: no second read
    assert storage.query("SELECT count(DISTINCT ts) n FROM venue_snapshots").n.iloc[0] == 1


def test_archive_rows_and_resumable_download(tmp_path):
    raw = {"ticker": "KXNBAPTS-26JAN15BOSMIA-MIATHERRO14-30", "event_ticker": "KXNBAPTS-26JAN15BOSMIA",
           "title": "Tyler Herro records 30+ points", "floor_strike": 29.5, "strike_type": "structured",
           "result": "scalar", "settlement_value_dollars": "0.2100", "volume_fp": "812.00",
           "open_time": "2026-01-15T08:00:00Z", "occurrence_datetime": "2026-01-16T03:30:00Z",
           "custom_strike": {"basketball_player": "uuid-1"}}
    row = market_row(raw, datetime(2026, 10, 18))
    assert (row["player"], row["team"], row["threshold"], row["settlement_value"]) == ("Tyler Herro", "MIA", 30, 0.21)
    assert row["tip_est"] == datetime(2026, 1, 16, 0, 30)
    candles = [{"end_period_ts": 1768521600, "yes_bid": {"close": "0.4400"}, "yes_ask": {"close": "0.4500"},
                "price": {"close": "0.4500", "mean": "0.4450"}, "volume": "12.00", "open_interest": "300.00"}]
    c = candle_rows(raw["ticker"], 1, candles)[0]
    assert (c["yes_bid_close"], c["yes_ask_close"], c["volume"]) == (0.44, 0.45, 12.0)

    class FakeArchive:
        calls = 0

        def markets(self, series):
            return [raw]

        def candles(self, ticker, start, end, interval):
            FakeArchive.calls += 1
            assert end == datetime(2026, 1, 16, 0, 30) and start == datetime(2026, 1, 15, 8, 0)   # opened < 24h ahead
            return candles

    store = HistoryStore(tmp_path / "h.duckdb")
    assert download(store=store, archive=FakeArchive(), log=lambda *_: None)["fetched_requests"] == 1
    assert download(store=store, archive=FakeArchive(), log=lambda *_: None)["fetched_requests"] == 0
    assert store.query("SELECT count(*) n FROM candles").n.iloc[0] == 1


def test_no_code_path_can_place_an_order():
    """Hard rule 4, enforced statically: venue modules only GET public market data."""
    venue_files = ["kalshi.py", "kalshi_history.py", "polymarket.py", "polymarket_us.py", "venues.py", "grade.py"]
    for name in venue_files:
        src = (PACKAGE / name).read_text()
        assert not re.search(r"\.(post|put|delete|patch)\(", src), name
        assert "https://api.polymarket.us" not in src, name         # the authenticated trading host
        for path in ("/portfolio", "/orders", "/order", "/balance", "/positions"):
            assert f'"{path}' not in src and f"'{path}" not in src, (name, path)
    for src in (p.read_text() for p in PACKAGE.glob("*.py")):
        assert not re.search(r"KALSHI_(API_)?KEY|POLYMARKET_(API_)?KEY|PRIVATE_KEY", src)
