"""Helpers for weekend digest muting and Sunday evening rollups."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo


def local_now(timezone: str, now: datetime | None = None) -> datetime:
    """Return ``now`` (or UTC now) converted to the app timezone."""
    value = now or datetime.now(tz=UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(ZoneInfo(timezone))


def is_weekend(timezone: str, now: datetime | None = None) -> bool:
    """Return True for Saturday or Sunday in the app timezone."""
    return local_now(timezone, now).weekday() >= 5


def is_saturday(timezone: str, now: datetime | None = None) -> bool:
    """Return True when local day is Saturday."""
    return local_now(timezone, now).weekday() == 5


def is_sunday(timezone: str, now: datetime | None = None) -> bool:
    """Return True when local day is Sunday."""
    return local_now(timezone, now).weekday() == 6


def same_local_date(
    left: datetime,
    right: datetime,
    *,
    timezone: str,
) -> bool:
    """Return True when both timestamps fall on the same local calendar day."""
    left_local = left
    right_local = right
    if left_local.tzinfo is None:
        left_local = left_local.replace(tzinfo=UTC)
    if right_local.tzinfo is None:
        right_local = right_local.replace(tzinfo=UTC)
    zone = ZoneInfo(timezone)
    return left_local.astimezone(zone).date() == right_local.astimezone(zone).date()
