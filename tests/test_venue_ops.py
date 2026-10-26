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
from cold_start_usage.venues import Fetchers, prior_exposure, scan
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


def test_an_old_ticket_still_counts_and_a_rescan_replaces_it(storage):
    snapshot_from_file(storage, events_response([synthetic_event()]), FETCHED)
    run_projections(storage, DAY, FETCHED, {})
    m = kalshi_market("MIAGANTETOKOUNMPO34", "Giannis Antetokounmpo", 30, 0.38, 0.40, 50, 50)
    f = Fetchers(kalshi_markets=lambda: [m])
    first = scan(storage, DAY, FETCHED + timedelta(minutes=1), f, tag="t-60m", bankroll=1000.0)
    t1 = first[first.decision == "actionable"].iloc[0]
    frac = t1.stake_usd / 1000
    # 24 minutes later the decision is past the 20-minute freshness window, but the ticket was sent.
    later = FETCHED + timedelta(minutes=25)
    prior = prior_exposure(storage, DAY, later, 1000.0)
    key = (t1.event_id, t1.player_id, "points")
    assert prior.issued == {key: pytest.approx(frac)}
    assert prior.slate == pytest.approx(frac) and prior.group[key[:2]] == pytest.approx(frac)
    # Rescanning the same game re-sizes his pick in place of that ticket, not on top of it.
    again = scan(storage, DAY, later, f, tag="t-15m", bankroll=1000.0)
    t2 = again[again.decision == "actionable"].iloc[0]
    assert t2.player_id == t1.player_id and t2.stake_usd == pytest.approx(t1.stake_usd)


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
    """Hard rule 4, enforced statically on every module in the package (the venue readers, the
    scan, decisions, distributions, the CLI, and anything added later): GETs of public market
    data only, no order or portfolio path, never the authenticated Polymarket US host."""
    modules = sorted(PACKAGE.glob("*.py"))
    assert {"kalshi.py", "kalshi_history.py", "polymarket.py", "polymarket_us.py", "venues.py", "grade.py",
            "decision.py", "distributions.py", "pipeline.py", "cli.py"} <= {p.name for p in modules}
    for path in modules:
        name, src = path.name, path.read_text()
        assert not re.search(r"\.(post|put|delete|patch)\(", src), name
        assert "https://api.polymarket.us" not in src and "//api.polymarket.us" not in src, name   # trading host
        for p in ("/portfolio", "/orders", "/order", "/balance", "/positions"):
            assert f'"{p}' not in src and f"'{p}" not in src, (name, p)
        assert not re.search(r"KALSHI_(API_)?KEY|POLYMARKET_(API_)?KEY|PRIVATE_KEY", src), name
        # Hard rule 2: SportsGameOdds' precomputed consensus fields are named only where they are dropped.
        if name != "sgo_client.py":
            assert not re.search(r"fairOdds|bookOdds|fairOverUnder|bookOverUnder", src), name


# --- regressions from the adversarial review -------------------------------------------
GIANNIS = lambda: kalshi_market("MIAGANTETOKOUNMPO34", "Giannis Antetokounmpo", 30, 0.38, 0.40, 50, 50)  # noqa: E731


def test_old_actionable_decisions_expire_and_a_failed_read_drops_them(storage):
    from cold_start_usage.venues import latest_venue_signals
    _actionable_slate(storage)                                   # scan at FETCHED + 1 min
    t0 = FETCHED + timedelta(minutes=1)
    assert (latest_venue_signals(storage, t0 + timedelta(minutes=5)).decision == "actionable").any()
    assert latest_venue_signals(storage, t0 + timedelta(minutes=25)).empty   # older than 20 min: gone

    def down():
        raise RuntimeError("rate limited")
    scan(storage, DAY, t0 + timedelta(minutes=10), Fetchers(kalshi_markets=down))
    # The failed read logged nothing, so no fresh decision supersedes the old one; it still expires.
    assert latest_venue_signals(storage, t0 + timedelta(minutes=21)).empty


def test_a_read_that_returns_after_tip_is_not_logged(storage):
    snapshot_from_file(storage, events_response([synthetic_event()]), FETCHED)
    run_projections(storage, DAY, FETCHED, {})
    f = Fetchers(kalshi_markets=lambda: [GIANNIS()], clock=lambda: TIP + timedelta(seconds=30))
    df = scan(storage, DAY, TIP - timedelta(minutes=5), f, tag="t-5m")   # tick before tip, answer after
    assert df.empty and storage.count("venue_signals") == 0 and storage.count("venue_snapshots") == 0
    assert any("after tip" in e for e in f.errors)


def test_failed_kalshi_read_leaves_the_checkpoint_open(storage):
    from cold_start_usage.pipeline import venue_due_plan
    snapshot_from_file(storage, events_response([synthetic_event()]), FETCHED)
    now = TIP - timedelta(minutes=58)

    def down():
        raise RuntimeError("429")
    scan(storage, DAY, now, Fetchers(kalshi_markets=down, pm_intl_event=lambda a, h, d: None), tag="t-60m")
    assert venue_due_plan(storage, now + timedelta(minutes=5)) != {}         # retried next tick
    scan(storage, DAY, now + timedelta(minutes=5), Fetchers(kalshi_markets=lambda: []), tag="t-60m")
    assert venue_due_plan(storage, now + timedelta(minutes=10)) == {}        # "no listing" counts as read


def test_auto_projection_error_does_not_stop_the_tick(storage, monkeypatch, capsys):
    snapshot_from_file(storage, events_response([synthetic_event()]), FETCHED)
    monkeypatch.setattr("cold_start_usage.venues.live_fetchers", lambda: Fetchers(kalshi_markets=lambda: [GIANNIS()]))
    monkeypatch.setattr(cli, "_client", lambda *a: (_ for _ in ()).throw(__import__(
        "cold_start_usage.sgo_client", fromlist=["MissingAPIKey"]).MissingAPIKey("no key")))

    def broken(*a, **k):
        raise ValueError("MIA: no scenario 'full_strength'")
    monkeypatch.setattr(cli, "run_projections", broken)
    args = cli.build_parser().parse_args(["snapshot", "--due", "--with-venues", "--with-projections"])
    assert cli.cmd_snapshot(args, storage, lambda: TIP - timedelta(minutes=58)) == 0
    out = capsys.readouterr().out
    assert "Auto-projection skipped" in out and "Venues (t-60m)" in out


def test_a_manual_scenario_replaces_the_whole_team_run(storage):
    from cold_start_usage.pipeline import latest_projections
    snapshot_from_file(storage, events_response([synthetic_event()]), FETCHED)
    run_projections(storage, DAY, FETCHED, {"MIA": "full_strength"})
    run_projections(storage, DAY, FETCHED + timedelta(minutes=5), {"MIA": "giannis_out"})
    lp = latest_projections(storage, "SYNTHETIC_MIN_MIA_20261021", FETCHED + timedelta(minutes=6))
    assert "Giannis Antetokounmpo" not in set(lp.player_name)             # not his stale full_strength row
    assert set(lp.scenario[lp.team == "MIA"]) == {"giannis_out"}


def test_fill_validation_and_corrections(storage, capsys):
    ticker, df = _actionable_slate(storage)
    sid = df[df.decision == "actionable"].signal_id.iloc[0]
    now = lambda: FETCHED + timedelta(minutes=5)  # noqa: E731
    p = cli.build_parser()
    assert cli.cmd_fill(p.parse_args(["fill", "--signal-id", sid, "--contracts", "10", "--price", "41"]), storage, now) == 2
    assert cli.cmd_fill(p.parse_args(["fill", "--venue", "kalshi", "--ticker", "KXNBAPTS-NOPE", "--side", "YES",
                                      "--contracts", "1", "--price", "0.4"]), storage, now) == 2
    assert cli.cmd_fill(p.parse_args(["fill", "--signal-id", sid, "--contracts", "10", "--price", "0.40"]), storage, now) == 0
    first = storage.query("SELECT fill_id FROM tickets").fill_id.iloc[0]
    assert cli.cmd_fill(p.parse_args(["fill", "--signal-id", sid, "--contracts", "8", "--price", "0.41",
                                      "--replaces", first]), storage, now) == 0
    storage.append("venue_settlements", [{"venue": "kalshi", "ticker": ticker, "result": "yes", "settlement_value": 1.0}])
    f = fills_graded(storage)
    assert len(f) == 1 and f.contracts.iloc[0] == 8                       # the correction only


def test_failed_slate_fetch_backs_off_instead_of_billing_every_tick(storage):
    from cold_start_usage.pipeline import slate_already_fetched
    d = DAY.isoformat()
    t = TIP - timedelta(hours=8)
    storage.append("api_calls", [{"ts": t, "endpoint": "/events/", "objects": 1, "note": f"slate:{d} | failed"}])
    assert slate_already_fetched(storage, DAY, t + timedelta(minutes=5))      # backing off
    assert not slate_already_fetched(storage, DAY, t + timedelta(minutes=61))  # one retry an hour later
    storage.append("api_calls", [{"ts": t + timedelta(hours=k), "endpoint": "/events/", "objects": 1,
                                  "note": f"slate:{d} | failed"} for k in (1, 2)])
    assert slate_already_fetched(storage, DAY, t + timedelta(hours=5))        # 3 failures: done for today


def test_live_venue_reads_refused_at_simulated_time(capsys, tmp_path):
    db = tmp_path / "sim.duckdb"
    assert cli.main(["--db", str(db), "--now", "2026-10-21T22:30:00Z", "venues", "--date", "2026-10-21"]) == 0
    assert "simulated" in capsys.readouterr().out
