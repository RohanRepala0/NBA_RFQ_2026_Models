"""The daily job: automatic rotations, one unattended run end to end on the synthetic slate,
the journal keeping committed days when the database starts fresh, and the alerts."""
from __future__ import annotations

import shutil
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from cold_start_usage import autorotation, config, daily, notify
from cold_start_usage.journal import season_summary, write_journal
from cold_start_usage.venues import Fetchers
from tests.conftest import FakeTransport
from tests.fixtures.synthetic import TIP, events_response, synthetic_event
from tests.test_venues import kalshi_market

DAY = TIP.date()


@pytest.fixture
def scenarios(tmp_path, monkeypatch):
    """A writable copy of the frozen scenarios (the job writes `auto` into TEAM.csv)."""
    d = tmp_path / "scenarios"
    shutil.copytree(config.SCENARIOS_DIR, d)
    monkeypatch.setattr(config, "SCENARIOS_DIR", d)
    return d


def _box(team: str, games: int, lines: dict[str, list[float]]) -> pd.DataFrame:
    """Box-score rows (played lines only, as features.history returns them), newest game first:
    lines[name][i] = minutes in game i (0 = didn't play, no row)."""
    rows = []
    for i in range(games):
        starts = datetime(2026, 11, 20) - timedelta(days=2 * i)
        for name, mins in lines.items():
            if mins[i] > 0:
                rows.append({"event_id": f"g{i}", "starts_at": starts, "team": team, "player_name": name,
                             "player_id": name.upper().replace(" ", "_") + "_1_NBA", "minutes": float(mins[i])})
    return pd.DataFrame(rows)


def test_to_total_reaches_240_with_nobody_over_the_cap():
    m = autorotation.to_total(pd.Series([40.0, 30.0, 30.0, 25.0, 20.0, 15.0, 10.0, 8.0]))
    assert m.sum() == pytest.approx(240.0) and m.max() <= autorotation.AUTO_CAP + 1e-9
    assert m.iloc[0] == autorotation.AUTO_CAP                       # a 40-minute average is capped
    big = autorotation.to_total(pd.Series([36.0, 36.0, 36.0, 36.0, 36.0, 30.0, 30.0, 30.0]))
    assert big.sum() == pytest.approx(240.0) and big.iloc[0] < 36.0  # an excess comes off in proportion


def test_auto_rotation_drops_players_who_left_and_deep_bench():
    box = _box("MIA", 10, {
        "Bam Adebayo": [34] * 10,
        "Andrew Wiggins": [32] * 10,
        "Gone Player": [0, 0, 0] + [30] * 7,          # missed each of the last 3: hurt or traded
        "Back Player": [20, 0, 0] + [0] * 7,          # one game, the latest: in, at his per-game share
        "Deep Bench": [4] * 10,                       # under 6 a game
        **{f"Rotation {k}": [24] * 10 for k in range(6)},
    })
    rows = autorotation.build(box, "MIA")
    names = set(rows.player)
    assert "Gone Player" not in names and "Deep Bench" not in names and "Back Player" not in names
    assert {"Bam Adebayo", "Andrew Wiggins"} <= names
    assert rows.proj_mpg.sum() == pytest.approx(240.0) and rows.proj_mpg.max() <= 37.0
    assert autorotation.build(_box("MIA", 2, {"Bam Adebayo": [34, 34]}), "MIA") is None   # too few games


def test_choose_writes_auto_and_a_hand_built_report_wins(scenarios):
    box = _box("MIA", 10, {"Bam Adebayo": [34] * 10, "Andrew Wiggins": [32] * 10,
                           **{f"Rotation {k}": [25] * 10 for k in range(7)}})
    choice, notes = autorotation.choose(box, ["MIA", "TOR"], DAY)
    assert choice["MIA"] == "auto" and choice["TOR"] == "full_strength"     # TOR: no games stored
    mia = pd.read_csv(scenarios / "MIA.csv")
    auto = mia[mia.scenario == "auto"]
    assert auto.proj_mpg.sum() == pytest.approx(240.0, abs=0.05) and {"giannis_out", "bam_out"} <= set(mia.scenario)
    autorotation.choose(box, ["MIA"], DAY)                                    # rewritten, not appended twice
    assert (pd.read_csv(scenarios / "MIA.csv").scenario == "auto").sum() == len(auto)
    hand = pd.DataFrame({"scenario": f"report_{DAY:%m%d}_b", "player": auto.player, "proj_mpg": auto.proj_mpg})
    pd.concat([mia, hand]).to_csv(scenarios / "MIA.csv", index=False)
    assert autorotation.choose(box, ["MIA"], DAY)[0]["MIA"] == f"report_{DAY:%m%d}_b"


class SlateTransport(FakeTransport):
    """The synthetic game for its own date and by id; every other date is an empty slate."""

    def __init__(self, final: bool = False):
        super().__init__(used=100, events=[])
        self.final = final

    def get(self, url, params, headers, timeout):
        if not url.endswith("/account/usage"):
            p = dict(params)
            hit = "eventIDs" in p or (p.get("startsAfter", "") <= TIP.strftime("%Y-%m-%dT%H:%M:%S")
                                      < p.get("startsBefore", ""))
            self.events = [events_response([synthetic_event(final=self.final)] if hit else [])]
        return super().get(url, params, headers, timeout)


def test_daily_run_end_to_end(storage, scenarios, tmp_path, make_client, monkeypatch):
    monkeypatch.setenv(config.BANKROLL_ENV, "5000")
    sent = []
    m = kalshi_market("MIAGANTETOKOUNMPO34", "Giannis Antetokounmpo", 30, 0.38, 0.40, 50, 50)
    fetchers = lambda: Fetchers(kalshi_markets=lambda: [m])                    # noqa: E731
    state = tmp_path / "state.json"
    transport = SlateTransport()
    client = make_client(transport, storage=storage)

    def go(now, **kw):
        return daily.run(storage, lambda: now, lambda: client, fetchers_factory=fetchers, state_path=state,
                         settle=kw.get("settle", lambda *a: 0), send=lambda *a: sent.append(a))

    morning = TIP - timedelta(hours=8)                    # nothing due yet: the slate, rotations, no reads
    assert go(morning) == 0
    assert len(storage.query("SELECT DISTINCT event_id FROM events")) == 1
    assert set(storage.query("SELECT DISTINCT scenario FROM projections").scenario) == {"full_strength"}
    assert set(storage.query("SELECT DISTINCT model_version FROM projections").model_version) == \
        {config.ROLLING_MODEL_VERSION}                    # the job prices with the rolling model
    assert config.PROJECTION_SOURCE == "season"           # ... and leaves the configured default alone
    before = storage.count("api_calls")

    t60 = TIP - timedelta(minutes=50)
    assert go(t60) == 0
    assert set(storage.query("SELECT DISTINCT tag FROM venue_snapshots").tag) == {"t-60m"}
    assert (config.BETS_DIR / "days" / DAY.isoformat() / "summary.md").exists()
    assert (config.BETS_DIR / "SEASON.md").exists()
    plays = [a for a in sent if a[0].startswith("PLAYS")]
    tickets = pd.read_csv(config.BETS_DIR / "ledger.csv")
    assert len(plays) == (1 if len(tickets) else 0)
    if len(tickets):
        assert "Giannis Antetokounmpo" in plays[0][1] and "cancel" in plays[0][1]
    assert storage.count("api_calls") > before            # the t-60m odds snapshot

    n_sent, n_rows = len(sent), storage.count("venue_snapshots")
    assert go(t60 + timedelta(minutes=2)) == 0            # nothing new due: no reads, no repeat alert
    assert len(sent) == n_sent and storage.count("venue_snapshots") == n_rows

    # Next morning: the game is final; grading stores results and settles, the journal updates.
    transport.final = True

    def settle(st, d, now):
        rows = [{"ts": now, "venue": "kalshi", "ticker": t, "result": "yes", "settlement_value": 1.0,
                 "settled_ts": now} for t in set(st.query("SELECT ticker FROM venue_signals").ticker.dropna())]
        return st.append("venue_settlements", rows)
    assert go(TIP + timedelta(hours=14), settle=settle) == 0
    assert storage.count("results") > 0
    graded = [a for a in sent if a[0] == "Graded"]
    assert len(graded) == 1 and str(DAY) in graded[0][1]
    led = pd.read_csv(config.BETS_DIR / "ledger.csv")
    assert (led.outcome != "pending").all()
    assert go(TIP + timedelta(hours=15), settle=settle) == 0
    assert len([a for a in sent if a[0] == "Graded"]) == 1     # a graded day is done


def test_without_a_key_the_job_still_settles_and_alerts_once(storage, tmp_path, monkeypatch):
    from cold_start_usage.sgo_client import MissingAPIKey
    sent = []

    def no_key():
        raise MissingAPIKey("Set the SPORTS_ODDS_API_KEY environment variable")
    for k in range(2):
        rc = daily.run(storage, lambda: TIP, no_key, fetchers_factory=Fetchers, state_path=tmp_path / "s.json",
                       settle=lambda *a: 0, send=lambda *a: sent.append(a))
        assert rc == 1
    assert len([a for a in sent if a[0] == "RUN PROBLEM"]) == 1    # once a day, not every run


def test_a_fresh_database_keeps_the_committed_record(storage, tmp_path):
    out = tmp_path / "bets"
    out.mkdir()
    shutil.copy(config.REPO_DIR / "bets" / "ledger.csv", out / "ledger.csv")
    shutil.copy(config.REPO_DIR / "bets" / "fills.csv", out / "fills.csv")
    original = (out / "ledger.csv").read_text()
    write_journal(storage, out)                                      # an empty database
    assert (out / "ledger.csv").read_text() == original
    season = (out / "SEASON.md").read_text()
    n = len(pd.read_csv(out / "ledger.csv"))
    assert f"| season | {n} |" in season and "## By stat" in season and "## By day" in season
    assert season == season_summary(original)                       # deterministic


def test_alerts_never_leak_the_topic(monkeypatch, capsys):
    topic = "ntfy-daily-test-TOPIC-9c1e"
    calls = []

    class Resp:
        status_code = 200

    def post(url, data, headers, timeout):
        calls.append((url, data, headers))
        return Resp()
    monkeypatch.delenv(notify.TOPIC_ENV, raising=False)
    monkeypatch.setattr(config, "REPO_DIR", config.REPO_DIR / "no-such-dir")
    assert notify.send("t", "b", post=post) is False and not calls       # no topic: nothing sent
    monkeypatch.setenv(notify.TOPIC_ENV, topic)
    assert notify.send("PLAYS – today", "body", "high", post=post) is True
    assert calls[0][0].endswith("/" + topic) and calls[0][2]["Title"].isascii()

    def boom(url, **k):
        raise ConnectionError(url)
    assert notify.send("t", "b", post=boom) is False
    assert topic not in capsys.readouterr().out


def test_the_budget_stop_is_a_notice_not_a_failure(storage, scenarios, tmp_path, make_client):
    sent = []
    client = make_client(SlateTransport(), hard_stop=50, storage=storage)      # 100 used: over the stop
    for k in range(2):
        rc = daily.run(storage, lambda: TIP - timedelta(hours=8), lambda: client, fetchers_factory=Fetchers,
                       state_path=tmp_path / "s.json", settle=lambda *a: 0, send=lambda *a: sent.append(a))
        assert rc == 0
    assert [a[0] for a in sent] == ["NOTICE"]                                  # once a day
    assert "budget" in sent[0][1]
