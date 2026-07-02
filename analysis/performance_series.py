"""Aggregate raw performance snapshots into chart periods (day / week / month)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from storage.models import PortfolioPerformanceSnapshot

ChartPeriod = Literal["week", "month", "all"]
BucketGranularity = Literal["day", "week", "month"]


@dataclass(frozen=True)
class ValueBar:
    """OHLC bar for one chart bucket (day, week, or month)."""

    period_start: datetime
    open: float
    high: float
    low: float
    close: float
    label: str


def aggregate_performance_bars(
    snapshots: list[PortfolioPerformanceSnapshot],
    *,
    period: ChartPeriod,
    timezone: str = "Asia/Hong_Kong",
    now: datetime | None = None,
) -> list[ValueBar]:
    """Collapse intraday snapshots into daily, weekly, or monthly OHLC bars."""
    ordered = sorted(snapshots, key=lambda row: _ensure_utc(row.timestamp))
    if not ordered:
        return []

    evaluated_at = _ensure_utc(now or ordered[-1].timestamp)
    tz = ZoneInfo(timezone)

    if period == "week":
        start_local = evaluated_at.astimezone(tz).date() - timedelta(days=6)
        filtered = [
            row
            for row in ordered
            if _local_date(row.timestamp, tz) >= start_local
        ]
        return _bars_from_buckets(
            filtered,
            granularity="day",
            tz=tz,
            reference=evaluated_at.astimezone(tz),
        )

    if period == "month":
        start_local = evaluated_at.astimezone(tz).date() - timedelta(days=29)
        filtered = [
            row
            for row in ordered
            if _local_date(row.timestamp, tz) >= start_local
        ]
        return _bars_from_buckets(
            filtered,
            granularity="week",
            tz=tz,
            reference=evaluated_at.astimezone(tz),
        )

    granularity = _auto_granularity(ordered, tz)
    return _bars_from_buckets(
        ordered,
        granularity=granularity,
        tz=tz,
        reference=evaluated_at.astimezone(tz),
    )


def _auto_granularity(
    snapshots: list[PortfolioPerformanceSnapshot],
    tz: ZoneInfo,
) -> BucketGranularity:
    """Pick bucket size for an all-time chart from the stored span."""
    first = _ensure_utc(snapshots[0].timestamp).astimezone(tz).date()
    last = _ensure_utc(snapshots[-1].timestamp).astimezone(tz).date()
    span_days = (last - first).days
    if span_days > 90:
        return "month"
    if span_days > 14:
        return "week"
    return "day"


def _bars_from_buckets(
    snapshots: list[PortfolioPerformanceSnapshot],
    *,
    granularity: BucketGranularity,
    tz: ZoneInfo,
    reference: datetime | None = None,
) -> list[ValueBar]:
    """Group snapshots and build OHLC bars in chronological order."""
    buckets: dict[date | tuple[int, int], list[PortfolioPerformanceSnapshot]] = {}
    bucket_starts: dict[date | tuple[int, int], datetime] = {}

    for row in snapshots:
        local = _ensure_utc(row.timestamp).astimezone(tz)
        if granularity == "day":
            key: date | tuple[int, int] = local.date()
            start = datetime.combine(local.date(), datetime.min.time(), tzinfo=tz)
        elif granularity == "week":
            key = (local.isocalendar().year, local.isocalendar().week)
            week_start = local.date() - timedelta(days=local.weekday())
            start = datetime.combine(week_start, datetime.min.time(), tzinfo=tz)
        else:
            key = (local.year, local.month)
            start = datetime(local.year, local.month, 1, tzinfo=tz)

        buckets.setdefault(key, []).append(row)
        bucket_starts.setdefault(key, start)

    bars: list[ValueBar] = []
    for key in sorted(buckets, key=_sort_bucket_key):
        group = buckets[key]
        open_, high, low, close = _ohlc(group)
        start = bucket_starts[key]
        bars.append(
            ValueBar(
                period_start=start.astimezone(UTC),
                open=open_,
                high=high,
                low=low,
                close=close,
                label=_bucket_label(start, granularity, reference=reference),
            )
        )
    return bars


def _ohlc(
    snapshots: list[PortfolioPerformanceSnapshot],
) -> tuple[float, float, float, float]:
    """Return open, high, low, close from time-ordered snapshots."""
    ordered = sorted(snapshots, key=lambda row: _ensure_utc(row.timestamp))
    values = [row.total_value for row in ordered]
    return values[0], max(values), min(values), values[-1]


def _bucket_label(
    start_local: datetime,
    granularity: BucketGranularity,
    *,
    reference: datetime | None = None,
) -> str:
    """Human-friendly axis label for one chart bucket."""
    if granularity == "day":
        bar_date = start_local.date()
        if reference is not None:
            ref_date = reference.astimezone(start_local.tzinfo).date()
            if bar_date == ref_date:
                return "Today"
            if bar_date == ref_date - timedelta(days=1):
                return "Yesterday"
        weekday = start_local.strftime("%a")
        return f"{weekday}\n{start_local.strftime('%-d %b')}"

    if granularity == "week":
        week_end = start_local.date() + timedelta(days=6)
        if start_local.month == week_end.month:
            return f"{start_local.strftime('%-d')}–{week_end.strftime('%-d %b')}"
        return f"{start_local.strftime('%-d %b')}–\n{week_end.strftime('%-d %b')}"

    return start_local.strftime("%b %Y")


def _local_date(timestamp: datetime, tz: ZoneInfo) -> date:
    return _ensure_utc(timestamp).astimezone(tz).date()


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _sort_bucket_key(key: date | tuple[int, int]) -> tuple[int, int]:
    if isinstance(key, date):
        return key.year, key.toordinal()
    return key
