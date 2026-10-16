"""When to snapshot: slate dates in ET and the T-6h / T-2h / T-60m / T-15m checkpoints."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pandas as pd

from .config import ET, SEASON_OPENER, SNAPSHOT_OFFSETS_MIN


def et_day_bounds(d: date) -> tuple[datetime, datetime]:
    """[start, end) of an ET calendar day, as naive UTC."""
    start = datetime.combine(d, time(0), tzinfo=ET).astimezone(timezone.utc).replace(tzinfo=None)
    end = datetime.combine(d + timedelta(days=1), time(0), tzinfo=ET).astimezone(timezone.utc).replace(tzinfo=None)
    return start, end


def iso_z(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def et_date(ts_utc) -> date:
    return pd.Timestamp(ts_utc).tz_localize("UTC").tz_convert(ET).date()


def week_of_season(d: date) -> int:
    return (d - SEASON_OPENER).days // 7 + 1


def due_tag(starts_at: datetime, now: datetime, taken: set[str]) -> str | None:
    """The most recent checkpoint already passed, if not yet taken. None after tip."""
    if now >= starts_at:
        return None
    minutes_to_tip = (starts_at - now).total_seconds() / 60
    passed = [(off, tag) for tag, off in SNAPSHOT_OFFSETS_MIN.items() if minutes_to_tip <= off]
    if not passed:
        return None
    tag = min(passed)[1]
    return None if tag in taken else tag


def current_timing(starts_at: datetime, now: datetime) -> str | None:
    """Which signal checkpoint (t-60m / t-15m) `now` falls under, ignoring what's taken."""
    if now >= starts_at:
        return None
    minutes_to_tip = (starts_at - now).total_seconds() / 60
    if minutes_to_tip <= SNAPSHOT_OFFSETS_MIN["t-15m"]:
        return "t-15m"
    if minutes_to_tip <= SNAPSHOT_OFFSETS_MIN["t-60m"]:
        return "t-60m"
    return "early"
