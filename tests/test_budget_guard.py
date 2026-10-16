from __future__ import annotations

import pytest
import requests

from cold_start_usage.sgo_client import (BudgetExceeded, BudgetGuard, MissingAPIKey, RateLimiter,
                                       SGOClient, SGOError, Usage)
from tests.conftest import FAKE_KEY, FakeTransport, usage_body
from tests.fixtures.synthetic import events_response, synthetic_event


def test_guard_allowance():
    g = BudgetGuard(2200)
    assert g.allowance(2000) == 200
    assert g.allowance(2000, local_used=2150) == 50          # the larger count wins
    with pytest.raises(BudgetExceeded):
        g.allowance(2200)
    with pytest.raises(BudgetExceeded):
        g.allowance(None)                                    # fail closed


def test_guard_blocks_request_at_hard_stop(make_client):
    transport = FakeTransport(used=2200)
    client = make_client(transport)
    with pytest.raises(BudgetExceeded):
        client.events({"leagueID": "NBA"})
    assert not [c for c in transport.calls if c[0].endswith("/events/")]   # never sent


def test_guard_caps_limit_to_remaining(make_client):
    transport = FakeTransport(used=2197)
    client = make_client(transport)
    client.events({"leagueID": "NBA"})
    events_call = [c for c in transport.calls if c[0].endswith("/events/")][0]
    assert events_call[1]["limit"] == 3


def test_pagination_stops_on_short_page_and_counts_objects(make_client):
    ev = synthetic_event()
    pages = [events_response([ev, ev], next_cursor="c1"), events_response([ev])]
    transport = FakeTransport(used=0, events=pages)
    client = make_client(transport)
    import cold_start_usage.config as config
    old = config.EVENTS_PAGE_LIMIT
    config.EVENTS_PAGE_LIMIT = 2
    try:
        res = client.events({"leagueID": "NBA"})
    finally:
        config.EVENTS_PAGE_LIMIT = old
    assert len(res.events) == 3 and res.objects == 3
    calls = [c for c in transport.calls if c[0].endswith("/events/")]
    assert len(calls) == 2 and calls[1][1]["cursor"] == "c1"


def test_empty_response_still_costs_one_object(make_client):
    client = make_client(FakeTransport(used=0, events=[events_response([])]))
    assert client.events({"leagueID": "NBA"}).objects == 1


def test_429_backs_off_then_succeeds(make_client):
    transport = FakeTransport(events=[(429, {"success": False}), events_response([synthetic_event()])])
    client = make_client(transport)
    res = client.events({"leagueID": "NBA"})
    assert len(res.events) == 1
    assert client.sleeps == [2.0]


def test_persistent_429_raises(make_client):
    transport = FakeTransport(events=[(429, {})] * 10)
    client = make_client(transport)
    with pytest.raises(SGOError, match="429"):
        client.events({"leagueID": "NBA"})
    assert client.sleeps == [2.0, 4.0, 8.0, 16.0]


def test_network_errors_retry():
    class Flaky(FakeTransport):
        def __init__(self):
            super().__init__()
            self.fail = 2

        def get(self, url, params, headers, timeout):
            if self.fail:
                self.fail -= 1
                raise requests.ConnectionError("boom")
            return super().get(url, params, headers, timeout)

    sleeps = []
    client = SGOClient(api_key=FAKE_KEY, transport=Flaky(), sleep=sleeps.append,
                       limiter=RateLimiter(per_minute=1000, sleep=sleeps.append))
    assert client.usage().objects_used == 100
    assert sleeps == [2.0, 4.0]


def test_usage_parses_spec_and_docs_field_names():
    for style in ("spec", "docs"):
        u = Usage.from_payload(usage_body(1234, style))
        assert u.objects_used == 1234 and u.objects_max == 2500
        assert u.requests_max_minute == 10


def test_api_key_never_exposed(make_client, monkeypatch):
    client = make_client(FakeTransport(events=[(401, {"error": "bad key"})]))
    assert FAKE_KEY not in repr(client)
    with pytest.raises(SGOError) as exc:
        client.events({"leagueID": "NBA"})
    assert FAKE_KEY not in str(exc.value)
    # Sent only as a header, never as a URL parameter.
    url, params, headers = client.transport.calls[-1]
    assert headers == {"x-api-key": FAKE_KEY} and FAKE_KEY not in str(params) + url


def test_missing_key(monkeypatch, tmp_path):
    monkeypatch.delenv("SPORTS_ODDS_API_KEY", raising=False)
    monkeypatch.setattr("cold_start_usage.config.REPO_DIR", tmp_path)
    with pytest.raises(MissingAPIKey):
        SGOClient()


def test_rate_limiter_waits_when_window_full():
    t = [0.0]
    slept = []

    def sleep(s):
        slept.append(s)
        t[0] += s

    rl = RateLimiter(per_minute=2, clock=lambda: t[0], sleep=sleep)
    rl.wait()
    rl.wait()
    rl.wait()
    assert slept and slept[0] == pytest.approx(60.05)
