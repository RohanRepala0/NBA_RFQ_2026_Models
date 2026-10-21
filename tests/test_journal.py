"""The bet journal (bets/): ticket selection, repeat flags, grading parity with grade.py, fill
kinds and corrections, deterministic output, and no secrets in any file."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from cold_start_usage import cli, config
from cold_start_usage.grade import venue_graded
from cold_start_usage.journal import build, fill_kind, write_journal

TIP1 = datetime(2026, 10, 21, 23, 0)        # 19:00 ET
TIP2 = datetime(2026, 10, 22, 2, 0)         # 22:00 ET, same ET slate
DAY = date(2026, 10, 21)
K1 = "KXNBAPTS-26OCT21MIATOR-TORAPLAYER1-20"
K2 = "KXNBAPTS-26OCT21MIATOR-TORAPLAYER1-25"
K3 = "KXNBAREB-26OCT21MIATOR-TORAPLAYER1-6"
K4 = "KXNBAAST-26OCT21MIATOR-TORAPLAYER1-4"
P1 = "astatc-nba-lal-gsw-2026-10-21-ast-bplay-gte8"


def _sig(sid, ts, tag, ticker, *, venue="kalshi", event="E1", player="A Player", pid="p1", team="TOR",
         stat="points", contract="20+ YES", side="YES", ask=0.40, decision="actionable", tip=TIP1, contracts=30.0,
         p_blend=0.50, ev_blend=0.08):
    cost = ask + 0.02
    return {"ts": ts, "signal_id": sid, "tag": tag, "event_id": event, "game": "MIA @ TOR" if event == "E1" else "GSW @ LAL",
            "player_id": pid, "player": player, "team": team, "venue": venue, "ticker": ticker, "event_ticker": None,
            "stat": stat, "contract": contract, "side": side, "quote_ts": ts, "tip_ts": tip, "bid": ask - 0.02,
            "ask": ask, "max_price": ask + 0.03, "size_at_edge": 100.0, "cost": cost, "consensus_mean": 21.5,
            "n_books": 4, "p_market": p_blend - 0.02, "model_mean": 22.4, "p_blend": p_blend,
            "ev_market": p_blend - 0.02 - cost, "ev_blend": ev_blend, "contracts": contracts,
            "stake_usd": round(contracts * cost, 2), "decision": decision, "reason": "test"}


def _seed(storage):
    storage.append("events", [
        {"ts": TIP1 - timedelta(hours=8), "event_id": "E1", "starts_at": TIP1, "home_abbr": "TOR", "away_abbr": "MIA",
         "cancelled": False},
        {"ts": TIP1 - timedelta(hours=8), "event_id": "E2", "starts_at": TIP2, "home_abbr": "LAL", "away_abbr": "GSW",
         "cancelled": False}])
    storage.append("projections", [
        {"ts": TIP1 - timedelta(hours=7), "event_id": "E1", "player_id": "p1", "team": "TOR", "scenario": "full_strength",
         "stat": "points", "mean": 20.0},
        {"ts": TIP1 - timedelta(hours=3), "event_id": "E1", "player_id": "p1", "team": "TOR", "scenario": "kawhi_out",
         "stat": "points", "mean": 22.4},
        {"ts": TIP1 - timedelta(hours=3), "event_id": "E1", "player_id": "p9", "team": "MIA", "scenario": "full_strength",
         "stat": "points", "mean": 18.0}])
    t6, t2, t60 = TIP1 - timedelta(hours=6), TIP1 - timedelta(hours=2), TIP1 - timedelta(minutes=60)
    storage.append("venue_signals", [
        _sig("a1", t6, "t-6h", K1),                                             # ticket: A points
        _sig("a2", t2, "t-2h", K1, ev_blend=0.09),                              # repeat of a1
        _sig("a3", t60, "t-60m", K2, contract="25+ YES", ask=0.20, p_blend=0.30),  # another rung, same player-stat
        _sig("r1", t2, "t-2h", K3, stat="rebounds", contract="6+ REB YES", ask=0.30, p_blend=0.40, contracts=50.0),
        _sig("x1", t2, "t-2h", K4, stat="assists", contract="4+ AST YES", decision="abstain"),
        _sig("b1", TIP2 - timedelta(minutes=60), "t-60m", P1, venue="polymarket_us", event="E2", player="B Play",
             pid="p2", team="LAL", stat="assists", contract="8+ AST NO", side="NO", ask=0.65, tip=TIP2,
             p_blend=0.74, contracts=20.0),
        _sig("z1", t2, "t-2h", K1, side="NO", contract="20+ NO", ask=0.62, decision="abstain"),
    ])
    snap = lambda ticker, ts, bid, ask, venue="kalshi", tip=TIP1: {  # noqa: E731
        "ts": ts, "tag": "t-5m", "venue": venue, "ticker": ticker, "tip_ts": tip, "yes_bid": bid, "yes_ask": ask}
    storage.append("venue_snapshots", [
        snap(K1, TIP1 - timedelta(minutes=5), 0.44, 0.46), snap(K2, TIP1 - timedelta(minutes=5), 0.19, 0.21),
        snap(K3, TIP1 - timedelta(minutes=5), 0.27, 0.29), snap(K4, TIP1 - timedelta(minutes=5), 0.50, 0.52),
        snap(P1, TIP2 - timedelta(minutes=5), 0.30, 0.34, venue="polymarket_us", tip=TIP2)])
    storage.append("venue_settlements", [
        {"venue": "kalshi", "ticker": K1, "result": "yes", "settlement_value": 1.0},
        {"venue": "kalshi", "ticker": K2, "result": "no", "settlement_value": 0.0},
        {"venue": "kalshi", "ticker": K3, "result": "no", "settlement_value": 0.0},
        {"venue": "kalshi", "ticker": K4, "result": "yes", "settlement_value": 1.0}])   # P1 not settled: pending

    p = cli.build_parser()

    def fill(argv, minutes):
        now = lambda: TIP1 - timedelta(minutes=minutes)  # noqa: E731
        assert cli.cmd_fill(p.parse_args(["fill", *argv]), storage, now) == 0

    fill(["--signal-id", "a2", "--contracts", "10", "--price", "0.41"], 100)                  # real
    fill(["--signal-id", "r1", "--contracts", "20", "--price", "0.30", "--paper"], 90)        # paper
    first_paper = storage.query("SELECT fill_id FROM tickets WHERE signal_id = 'r1'").fill_id.iloc[0]
    fill(["--signal-id", "r1", "--contracts", "25", "--price", "0.30", "--replaces", first_paper], 80)  # its correction
    fill(["--venue", "kalshi", "--ticker", K4, "--side", "YES", "--contracts", "5", "--price", "0.51"], 70)
    fill(["--venue", "polymarket_us", "--ticker", P1, "--side", "NO", "--contracts", "4", "--price", "0.66",
          "--paper", "--note", "sim"], 60)
    return first_paper


def _read(path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def test_tickets_are_the_first_actionable_per_player_game_stat_and_repeats_are_flagged(storage, tmp_path):
    _seed(storage)
    write_journal(storage, tmp_path / "bets")
    led = _read(tmp_path / "bets" / "ledger.csv")
    assert list(led.signal_id) == ["a1", "r1", "b1"]                     # by tip, then first seen
    assert set(led.signal_id) == set(venue_graded(storage, DAY, DAY).signal_id)
    assert list(led.checkpoint) == ["t-6h", "t-2h", "t-60m"]
    assert led.tip_et.iloc[0] == "2026-10-21 19:00" and led.tip_utc.iloc[0] == "2026-10-21T23:00:00Z"
    day = tmp_path / "bets" / "days" / "2026-10-21"
    t = _read(day / "tickets.csv").set_index("signal_id")
    assert "x1" not in t.index and "z1" not in t.index                   # abstains are not tickets
    assert t.flag["a1"] == "ticket" and t.flag["r1"] == "ticket" and t.flag["b1"] == "ticket"
    assert t.flag["a2"] == "repeat of a1"
    assert t.flag["a3"] == "new contract after ticket a1"


def test_results_match_grade_venue_graded(storage, tmp_path):
    _seed(storage)
    write_journal(storage, tmp_path)
    res = _read(tmp_path / "days" / "2026-10-21" / "results.csv").set_index("signal_id")
    g = venue_graded(storage, DAY, DAY).set_index("signal_id")
    for sid in ("a1", "r1"):
        assert float(res.pnl_per_contract[sid]) == pytest.approx(g.pnl_per_contract[sid], abs=1e-4)
        assert float(res.clv[sid]) == pytest.approx(g.clv_venue[sid], abs=1e-4)
        assert float(res.close_mid[sid]) == pytest.approx(g.close_mid[sid], abs=1e-4)
        assert float(res.pnl_suggested_usd[sid]) == pytest.approx(g.contracts[sid] * g.pnl_per_contract[sid], abs=0.005)
    assert res.result["a1"] == "yes" and res.outcome["a1"] == "won"
    assert res.outcome["r1"] == "lost" and res.pnl_per_contract["r1"] == "-0.3200"
    assert res.clv["a1"] == "0.0500"                                    # close mid 45c vs a 40c entry
    assert float(res.close_mid["b1"]) == pytest.approx(0.68)            # a NO close is 1 - the YES mid
    assert res.result["b1"] == "pending" and res.pnl_per_contract["b1"] == ""
    summary = (tmp_path / "days" / "2026-10-21" / "summary.md").read_text()
    assert "Ticket b1" in summary and "pending" in summary
    assert "| TOR | MIA @ TOR | kawhi_out |" in summary and "| yes |" in summary
    assert "2 settled, 1 pending" in summary


def test_fill_kinds_paper_flag_and_corrections(storage, tmp_path):
    first_paper = _seed(storage)
    notes = storage.query("SELECT note FROM tickets ORDER BY ts").note.tolist()
    assert notes[1] == "paper" and notes[4] == "paper: sim"             # --paper alone, and with --note
    write_journal(storage, tmp_path)
    f = _read(tmp_path / "fills.csv")
    assert len(f) == 5                                                   # the superseded fill is kept
    by = f.set_index("fill_id")
    assert by.status[first_paper] == "superseded" and by.pnl_usd[first_paper] == ""
    corr = f[f.replaces == first_paper].iloc[0]
    assert by.superseded_by[first_paper] == corr.fill_id
    assert corr.kind == "paper" and corr.status == "current"            # a bare correction keeps the kind
    assert float(corr.pnl_usd) == pytest.approx(-25 * 0.30 - float(corr.fees_usd))
    assert f[f.signal_id == "a2"].kind.iloc[0] == "real"
    disc = f[f.ticker == K4].iloc[0]
    assert disc.kind == "discretionary" and disc.ticket_signal_id == "" and disc.matches_ticket == "no"
    assert f[f.ticker == P1].kind.iloc[0] == "paper"
    led = _read(tmp_path / "ledger.csv").set_index("signal_id")
    assert led.filled_contracts["a1"] == "10" and led.fill_avg_price["a1"] == "0.4100" and led.fill_kind["a1"] == "real"
    assert led.filled_contracts["r1"] == "25" and led.fill_kind["r1"] == "paper"
    assert led.fill_pnl_usd["b1"] == ""                                  # filled but unsettled
    # The kind rule on its own.
    assert fill_kind("Paper test", "s", True) == "paper"
    assert fill_kind("discretionary: hunch", "s", True) == "discretionary"
    assert fill_kind(None, None, False) == "discretionary"
    assert fill_kind(None, None, True) == "real"                         # logged by ticker on an actionable contract
    assert fill_kind(None, "s", True) == "real"


def test_output_is_deterministic(storage, tmp_path):
    _seed(storage)
    a, b = tmp_path / "a", tmp_path / "b"
    first = write_journal(storage, a)
    write_journal(storage, b)
    files = sorted(p.relative_to(a) for p in a.rglob("*") if p.is_file())
    assert files == sorted(p.relative_to(b) for p in b.rglob("*") if p.is_file())
    assert len(files) == 5 and len(first["written"]) == 5
    for rel in files:
        assert (a / rel).read_bytes() == (b / rel).read_bytes()
    assert write_journal(storage, a)["written"] == []                    # an unchanged rebuild touches nothing
    one = write_journal(storage, tmp_path / "c", dates=[DAY, date(2026, 10, 25)])
    assert one["days"] == [DAY] and one["skipped"] == [date(2026, 10, 25)]


def test_no_secret_reaches_any_file(storage, tmp_path, monkeypatch, capsys):
    key, topic = "sk-journal-test-KEY-7f3a9c", "ntfy-journal-test-TOPIC-41b2"
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".env").write_text(f"SPORTS_ODDS_API_KEY={key}\nNTFY_TOPIC={topic}\n")
    monkeypatch.setattr(config, "REPO_DIR", repo)
    monkeypatch.setenv("SPORTS_ODDS_API_KEY", key)
    monkeypatch.setenv("NTFY_TOPIC", topic)
    _seed(storage)
    out = tmp_path / "bets"
    args = cli.build_parser().parse_args(["journal", "--all", "--out", str(out)])
    assert cli.cmd_journal(args, storage, lambda: TIP2 + timedelta(hours=10)) == 0
    printed = capsys.readouterr().out
    files = [p for p in out.rglob("*") if p.is_file()]
    assert len(files) == 5
    for p in files:
        text = p.read_text()
        assert key not in text and topic not in text, p
    assert key not in printed and topic not in printed


def test_cli_journal_defaults_and_grade_splits_fills_by_kind(storage, capsys):
    _seed(storage)
    p = cli.build_parser()
    with pytest.raises(SystemExit):
        p.parse_args(["journal", "--all", "--date", "2026-10-21"])
    assert cli.cmd_journal(p.parse_args(["journal", "--date", "2026-10-21"]), storage, lambda: TIP2) == 0
    assert (config.BETS_DIR / "days" / "2026-10-21" / "summary.md").exists()   # the default out (tmp in tests)
    capsys.readouterr()
    cli._grade_venues(storage, DAY, TIP2 + timedelta(hours=10), offline=True)
    line = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("Your fills")][0]
    assert "real 1" in line and "paper 2" in line and "discretionary 1" in line
    j = build(storage)
    assert len(j.tickets) == 3 and len(j.actionable) == 5 and len(j.fills) == 5
