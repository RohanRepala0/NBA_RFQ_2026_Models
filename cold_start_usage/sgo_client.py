"""SportsGameOdds REST client: rate limit, retries with 429 backoff, budget guard,
and the parse-time book allowlist filter.

Verified against https://sportsgameodds.com/openapi.json (v2.0.0):
- auth header `x-api-key` (the key is never put in a URL, printed or logged)
- GET /events/ params used: leagueID, oddsAvailable, oddID, includeOpposingOdds,
  bookmakerID, eventIDs, startsAfter, startsBefore, finalized, limit, cursor
- per-book quotes at odds.<oddID>.byBookmaker.<bookmakerID>:
  odds, overUnder, available, isMainLine, lastUpdatedAt
- billing: 1 object per event returned; every response costs at least 1 object
"""
from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

import requests

from . import config
from .config import is_allowed_book


class SGOError(RuntimeError):
    pass


class MissingAPIKey(SGOError):
    pass


class BudgetExceeded(SGOError):
    pass


# Fields kept from each event / odd / per-book quote. Everything else is dropped
# at parse time, including SportsGameOdds' precomputed consensus fields
# (fairOdds, bookOdds, fairOverUnder, ...), which are computed across every book
# they carry rather than our allowlist (hard rule 2).
EVENT_FIELDS = ("eventID", "aliases", "sportID", "leagueID", "type", "status",
                "teams", "players", "odds", "results")
ODD_FIELDS = ("oddID", "opposingOddID", "marketName", "statID", "statEntityID",
              "periodID", "betTypeID", "sideID", "playerID", "started", "ended",
              "cancelled", "score")
QUOTE_FIELDS = ("odds", "overUnder", "spread", "available", "isMainLine", "lastUpdatedAt",
                "openOdds", "closeOdds", "openOverUnder", "closeOverUnder")


def off_list_book_count(event: dict) -> int:
    """How many distinct bookmakerIDs in a raw event are not on the allowlist (count only)."""
    seen = set()
    for odd in (event.get("odds") or {}).values():
        seen.update(b for b in (odd.get("byBookmaker") or {}) if not is_allowed_book(b))
    return len(seen)


def filter_event(event: dict) -> dict:
    """Keep only allowlisted books and the fields this project uses."""
    out = {k: event[k] for k in EVENT_FIELDS if k in event and k != "odds"}
    week = (event.get("info") or {}).get("seasonWeek")
    if week is not None:
        out["info"] = {"seasonWeek": week}
    odds = {}
    for odd_id, odd in (event.get("odds") or {}).items():
        kept = {k: odd[k] for k in ODD_FIELDS if k in odd}
        kept["byBookmaker"] = {
            book.lower(): {k: q[k] for k in QUOTE_FIELDS if k in q}
            for book, q in (odd.get("byBookmaker") or {}).items() if is_allowed_book(book)
        }
        odds[odd_id] = kept
    out["odds"] = odds
    return out


def _num(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    return None   # "unlimited", "n/a", missing


@dataclass
class Usage:
    tier: str | None
    is_active: bool | None
    objects_used: int | None        # this month, per the server
    objects_max: int | None         # plan cap (None = unlimited / unknown)
    requests_this_minute: int | None
    requests_max_minute: int | None

    @classmethod
    def from_payload(cls, payload: dict) -> "Usage":
        data = payload.get("data", payload) or {}
        limits = data.get("rateLimits", {}) or {}

        def pick(interval: str, *names: str) -> int | None:
            block = limits.get(interval, {}) or {}
            for n in names:   # the OpenAPI spec and the prose docs use different names
                if n in block:
                    return _num(block[n])
            return None

        return cls(
            tier=data.get("tier"),
            is_active=data.get("isActive"),
            objects_used=pick("per-month", "current-entities", "currentIntervalEntities"),
            objects_max=pick("per-month", "max-entities", "maxEntitiesPerInterval"),
            requests_this_minute=pick("per-minute", "current-requests", "currentIntervalRequests"),
            requests_max_minute=pick("per-minute", "max-requests", "maxRequestsPerInterval"),
        )


class BudgetGuard:
    """Fail-closed monthly object budget. Uses the larger of server and local counts."""

    def __init__(self, hard_stop: int = config.MONTHLY_OBJECT_HARD_STOP):
        self.hard_stop = hard_stop

    def allowance(self, server_used: int | None, local_used: int = 0) -> int:
        if server_used is None:
            raise BudgetExceeded("Could not read objects used from /account/usage; refusing to spend")
        used = max(server_used, local_used)
        remaining = self.hard_stop - used
        if remaining <= 0:
            raise BudgetExceeded(f"Monthly hard stop reached: {used} objects used, stop at {self.hard_stop}")
        return remaining


class RateLimiter:
    """At most `per_minute` requests in any rolling 60 seconds."""

    def __init__(self, per_minute: int = config.REQUESTS_PER_MINUTE,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.per_minute, self.clock, self.sleep = per_minute, clock, sleep
        self._stamps: deque[float] = deque()

    def wait(self) -> None:
        now = self.clock()
        while self._stamps and now - self._stamps[0] >= 60:
            self._stamps.popleft()
        if len(self._stamps) >= self.per_minute:
            self.sleep(60 - (now - self._stamps[0]) + 0.05)
            return self.wait()
        self._stamps.append(self.clock())


class RequestsTransport:
    def __init__(self):
        self._session = requests.Session()

    def get(self, url: str, params: dict, headers: dict, timeout: float):
        resp = self._session.get(url, params=params, headers=headers, timeout=timeout)
        try:
            body = resp.json()
        except ValueError:
            body = None
        return resp.status_code, dict(resp.headers), body


def load_api_key() -> str | None:
    key = os.environ.get(config.API_KEY_ENV)
    if key:
        return key.strip()
    env_file = config.REPO_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            name, sep, value = line.partition("=")
            if sep and name.strip() == config.API_KEY_ENV:
                return value.strip().strip('"').strip("'") or None
    return None


Ledger = Callable[[str, dict, int, int, str], None]


@dataclass
class EventsResult:
    events: list[dict]
    objects: int
    usage_before: Usage
    notices: list[str]
    off_list_books: int = 0


class SGOClient:
    def __init__(self, api_key: str | None = None, *, transport=None,
                 guard: BudgetGuard | None = None, limiter: RateLimiter | None = None,
                 ledger: Ledger | None = None, sleep: Callable[[float], None] = time.sleep,
                 local_used: Callable[[], int] | None = None):
        key = api_key or load_api_key()
        if not key:
            raise MissingAPIKey(f"Set the {config.API_KEY_ENV} environment variable (or .env)")
        self.__key = key
        self.transport = transport or RequestsTransport()
        self.guard = guard or BudgetGuard()
        self.limiter = limiter or RateLimiter(sleep=sleep)
        self.ledger = ledger
        self.sleep = sleep
        self.local_used = local_used or (lambda: 0)

    def __repr__(self) -> str:
        return "SGOClient(api_key=<hidden>)"

    def _request(self, path: str, params: dict) -> dict:
        url = f"{config.API_BASE}{path}"
        params = {k: v for k, v in params.items() if v is not None}
        delay = 2.0
        for attempt in range(config.MAX_RETRIES + 1):
            self.limiter.wait()
            try:
                status, headers, body = self.transport.get(
                    url, params, {"x-api-key": self.__key}, config.REQUEST_TIMEOUT_S)
            except requests.RequestException as exc:
                if attempt == config.MAX_RETRIES:
                    raise SGOError(f"GET {path} failed after retries: {type(exc).__name__}") from None
                self.sleep(delay)
                delay *= 2
                continue
            if status == 200 and isinstance(body, dict):
                return body
            if status == 429 or status >= 500:
                if attempt == config.MAX_RETRIES:
                    raise SGOError(f"GET {path}: HTTP {status} after {attempt + 1} attempts")
                retry_after = _num((headers or {}).get("Retry-After"))
                self.sleep(float(retry_after) if retry_after else delay)
                delay *= 2
                continue
            message = (body or {}).get("error") if isinstance(body, dict) else None
            raise SGOError(f"GET {path}: HTTP {status}{': ' + str(message) if message else ''}")
        raise SGOError(f"GET {path}: retries exhausted")

    def _log(self, endpoint: str, params: dict, status: int, objects: int, note: str = "") -> None:
        if self.ledger:
            self.ledger(endpoint, params, status, objects, note)

    def usage(self) -> Usage:
        body = self._request("/account/usage", {})
        usage = Usage.from_payload(body)
        self._log("/account/usage", {}, 200, config.USAGE_CALL_OBJECTS,
                  f"server_objects_used={usage.objects_used}")
        return usage

    def players(self, team_id: str, note: str = "") -> list[dict]:
        """GET /players/ for one team (roster + playerIDs). Billed as objects; guarded."""
        usage = self.usage()
        allowance = self.guard.allowance(usage.objects_used, self.local_used())
        params = {"teamID": team_id, "limit": min(100, allowance)}
        body = self._request("/players/", params)
        data = body.get("data") or []
        self._log("/players/", params, 200, max(1, len(data)), note or f"players:{team_id}")
        return data

    def events(self, params: dict, max_objects: int | None = None, note: str = "") -> EventsResult:
        """GET /events/ with the budget guard. Events are allowlist-filtered before return."""
        usage = self.usage()
        allowance = self.guard.allowance(usage.objects_used, self.local_used())
        cap = min(allowance, max_objects) if max_objects else allowance
        events, notices, spent, cursor, off_list = [], [], 0, None, 0
        while spent < cap:
            page_limit = max(1, min(config.EVENTS_PAGE_LIMIT, cap - spent))
            page_params = {**params, "limit": page_limit, "cursor": cursor}
            try:
                body = self._request("/events/", page_params)
            except SGOError:
                # Observed live: a rejected /events request (HTTP 400) is still billed.
                self._log("/events/", {k: v for k, v in page_params.items() if v is not None},
                          0, 1, (note + " | failed").strip(" |"))
                raise
            raw = body.get("data") or []
            off_list = max([off_list] + [off_list_book_count(e) for e in raw])
            data = [filter_event(e) for e in raw]
            del raw, body["data"]
            cost = max(1, len(data))
            spent += cost
            self._log("/events/", {k: v for k, v in page_params.items() if v is not None},
                      200, cost, note)
            if body.get("notice"):
                notices.append(str(body["notice"]))
            events.extend(data)
            cursor = body.get("nextCursor")
            if not cursor or len(data) < page_limit:
                break
        return EventsResult(events=events, objects=spent, usage_before=usage,
                            notices=notices, off_list_books=off_list)
