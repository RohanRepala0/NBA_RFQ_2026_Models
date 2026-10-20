"""End-to-end dry run on the synthetic slate, plus log-before-outcome and append-only rules."""
from __future__ import annotations

from datetime import timedelta

import pytest

from cold_start_usage.cli import main
from cold_start_usage.grade import graded_signals, summarize
from cold_start_usage.pipeline import (fetch_results, run_projections, run_signals, snapshot_due,
                                     snapshot_from_file)
from cold_start_usage.report import build_report, write_report
from cold_start_usage.consensus import sgo_target_quotes
from tests.conftest import FakeTransport
from tests.fixtures.synthetic import EVENT_ID, FETCHED, TIP, events_response, synthetic_event

DAY = TIP.date()


def load_slate(storage, now=FETCHED):
    snapshot_from_file(storage, events_response([synthetic_event(now)]), now)


def test_full_dry_run(storage, make_client):
    load_slate(storage)
    t1 = FETCHED + timedelta(minutes=1)
    table, msgs = run_projections(storage, DAY, t1, {"MIA": "full_strength"})
    assert not [m for m in msgs if "match" in m]                      # every player mapped to an ID
    assert storage.count("projections") == 11 * 3                     # one row per player and stat
    assert storage.query("SELECT count(*) n FROM projections WHERE stat = 'points'").n.iloc[0] == 11
    assert table.spc_new.notna().all()                                # spacing reported
    sig, _ = run_signals(storage, DAY, t1 + timedelta(minutes=1))
    assert len(sig) == 11 and storage.count("signals") == 11
    reasons = dict(zip(sig.player_name, sig.reason))
    assert reasons["Pelle Larsson"].startswith("stale quote")
    assert reasons["Dru Smith"].startswith("only 1 priced reference book")
    assert reasons["Nick Richards"].startswith("no market")
    assert set(sig.decision) <= {"paper", "abstain"}
    assert (sig.edge.dropna() >= 0).all()

    # SportsGameOdds-carried venue prices keep the "target" role and never enter the consensus.
    assert set(sgo_target_quotes(storage, EVENT_ID).book) == {"kalshi"}

    transport = FakeTransport(events=[events_response([synthetic_event(TIP + timedelta(hours=3), final=True)])])
    objects, n, _ = fetch_results(make_client(transport, storage=storage), storage, DAY, TIP + timedelta(hours=12))
    assert objects == 1 and n == 10                                   # Dru Smith DNP: no result row
    g = graded_signals(storage, DAY, DAY)
    s = summarize(g)
    assert s["graded"] > 0 and s["brier_model"] is not None and s["brier_market"] is not None
    assert g[g.player_name == "Giannis Antetokounmpo"].actual_points.iloc[0] == 31
    # A second grade run does not refetch (results already stored).
    assert fetch_results(make_client(FakeTransport(), storage=storage), storage, DAY, TIP)[0] == 0

    md = build_report(storage, DAY, DAY)
    for section in ("## Summary", "## Calibration", "## By team", "## New team vs incumbent",
                    "## CLV by week of season"):
        assert section in md
    assert write_report(storage, DAY, DAY).exists()


def test_nothing_is_logged_after_tip(storage):
    load_slate(storage)
    late = TIP + timedelta(minutes=1)
    _, msgs = run_projections(storage, DAY, late, {})
    assert storage.count("projections") == 0 and any("already tipped" in m for m in msgs)
    run_projections(storage, DAY, FETCHED, {})
    _, msgs = run_signals(storage, DAY, late)
    assert storage.count("signals") == 0 and any("already tipped" in m for m in msgs)


def test_signals_only_use_projections_logged_before_them(storage):
    load_slate(storage)
    run_projections(storage, DAY, FETCHED + timedelta(minutes=10), {})
    sig, _ = run_signals(storage, DAY, FETCHED + timedelta(minutes=5))
    assert sig.empty


def test_storage_is_append_only(storage):
    for sql in ("UPDATE signals SET edge = 1", "DELETE FROM signals", "DROP TABLE signals",
                "INSERT INTO signals (event_id) VALUES ('x')", "SELECT 1; DELETE FROM signals"):
        with pytest.raises(PermissionError):
            storage.query(sql)
    assert not any(hasattr(storage, m) for m in ("update", "delete", "execute", "overwrite"))
    run_projections(storage, DAY, FETCHED, {})  # no events yet: nothing to do, nothing raised


def test_projection_rows_are_kept_when_rerun(storage):
    load_slate(storage)
    run_projections(storage, DAY, FETCHED, {"MIA": "full_strength"})
    run_projections(storage, DAY, FETCHED + timedelta(minutes=30), {"MIA": "giannis_out"})
    df = storage.query("SELECT scenario, count(*) n FROM projections WHERE stat = 'points' GROUP BY scenario "
                       "ORDER BY scenario")
    assert dict(zip(df.scenario, df.n)) == {"full_strength": 11, "giannis_out": 10}


def test_due_snapshots_fetch_once_per_checkpoint(storage, make_client):
    transport = FakeTransport(events=[events_response([synthetic_event(TIP - timedelta(hours=7))])])
    client = make_client(transport, storage=storage)
    out = snapshot_due(client, storage, TIP - timedelta(hours=7))              # slate only
    assert out["slate"] and out["due"] == {}
    transport.events = [events_response([synthetic_event(TIP - timedelta(minutes=58))])]
    out = snapshot_due(client, storage, TIP - timedelta(minutes=58))
    assert out["due"] == {EVENT_ID: "t-60m"}
    n_calls = len(transport.calls)
    out = snapshot_due(client, storage, TIP - timedelta(minutes=55))           # already taken
    assert out["due"] == {} and len(transport.calls) == n_calls                # no API call at all
    events_calls = [c for c in transport.calls if c[0].endswith("/events/")]
    assert events_calls[-1][1]["eventIDs"] == EVENT_ID


def test_now_flag_refused_on_the_real_log(capsys):
    assert main(["--now", "2026-10-21T22:30:00Z", "signals"]) == 2
    assert "never back-dated" in capsys.readouterr().out


def test_due_with_signals_logs_at_checkpoint(storage, make_client, tmp_path, capsys, monkeypatch):
    load_slate(storage, TIP - timedelta(hours=7))
    storage.append("api_calls", [{"endpoint": "/events/", "objects": 1, "note": f"slate:{DAY.isoformat()}"}])
    run_projections(storage, DAY, TIP - timedelta(minutes=70), {})
    transport = FakeTransport(events=[events_response([synthetic_event(TIP - timedelta(minutes=58))])])
    client = make_client(transport, storage=storage)
    monkeypatch.setattr("cold_start_usage.cli._client", lambda *a: client)
    from cold_start_usage import cli
    args = cli.build_parser().parse_args(["snapshot", "--due", "--with-signals"])
    assert cli.cmd_snapshot(args, storage, lambda: TIP - timedelta(minutes=58)) == 0
    assert "Sportsbook signals at t-60m: 11 logged" in capsys.readouterr().out
    assert set(storage.query("SELECT DISTINCT timing FROM signals").timing) == {"t-60m"}
