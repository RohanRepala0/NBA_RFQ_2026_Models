from __future__ import annotations

import copy
from pathlib import Path

import pytest

from nba_cold_start.sgo_client import BudgetGuard, RateLimiter, SGOClient
from nba_cold_start.storage import Storage
from tests.fixtures.synthetic import events_response, synthetic_event

FAKE_KEY = "test-key-should-never-appear-0123456789"


def usage_body(used: int, style: str = "spec") -> dict:
    if style == "spec":
        month = {"max-requests": "unlimited", "current-requests": 3, "max-entities": 2500, "current-entities": used}
        minute = {"max-requests": 10, "current-requests": 1, "max-entities": "unlimited", "current-entities": 0}
    else:   # the naming used in the prose docs
        month = {"maxRequestsPerInterval": "unlimited", "maxEntitiesPerInterval": 2500,
                 "currentIntervalRequests": "n/a", "currentIntervalEntities": used}
        minute = {"maxRequestsPerInterval": 10, "currentIntervalRequests": 1,
                  "maxEntitiesPerInterval": "unlimited", "currentIntervalEntities": "n/a"}
    return {"success": True, "data": {"keyID": "k", "tier": "amateur", "isActive": True,
                                      "rateLimits": {"per-minute": minute, "per-month": month}}}


class FakeTransport:
    """Scripted responses. `events` is a list of bodies (or (status, body)) served in order."""

    def __init__(self, used: int = 100, events: list | None = None):
        self.used = used
        self.events = list(events if events is not None else [events_response([synthetic_event()])])
        self.calls: list[tuple[str, dict, dict]] = []

    def get(self, url, params, headers, timeout):
        self.calls.append((url, dict(params), dict(headers)))
        if url.endswith("/account/usage"):
            return 200, {}, usage_body(self.used)
        item = self.events.pop(0) if self.events else events_response([])
        status, body = item if isinstance(item, tuple) else (200, item)
        if status == 200:
            self.used += max(1, len(body.get("data", [])))
        return status, {}, copy.deepcopy(body)


@pytest.fixture(autouse=True)
def _isolated_output_dirs(tmp_path, monkeypatch):
    """Tests never write into the repo's data/ or reports/ folders."""
    from nba_cold_start import config
    monkeypatch.setattr(config, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(config, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(config, "BOOKS_FILE", tmp_path / "books.json")   # undiscovered by default
    # Pin model inputs to frozen copies so editing live data/ or scenarios/ never moves a test.
    frozen = Path(__file__).resolve().parent / "fixtures" / "regression"
    monkeypatch.setattr(config, "PLAYERS_CSV", frozen / "players_2025_26.csv")
    monkeypatch.setattr(config, "SCENARIOS_DIR", frozen / "scenarios")


@pytest.fixture
def storage():
    s = Storage(":memory:")
    yield s
    s.close()


@pytest.fixture
def make_client():
    def _make(transport: FakeTransport, hard_stop: int = 2200, storage: Storage | None = None):
        from nba_cold_start.pipeline import ledger_for
        from nba_cold_start.storage import utcnow
        sleeps: list[float] = []
        client = SGOClient(api_key=FAKE_KEY, transport=transport, guard=BudgetGuard(hard_stop),
                           limiter=RateLimiter(per_minute=1000, sleep=sleeps.append),
                           sleep=sleeps.append,
                           ledger=ledger_for(storage, utcnow) if storage else None,
                           local_used=(lambda: storage.objects_used_this_month()) if storage else None)
        client.sleeps = sleeps
        return client
    return _make
