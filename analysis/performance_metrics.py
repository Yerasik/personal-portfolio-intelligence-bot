"""Performance return and drawdown calculations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from storage.models import PerformanceHistory, PortfolioPerformanceSnapshot


@dataclass(frozen=True)
class PerformanceMetrics:
    """Computed portfolio performance statistics."""

    current_value: float
    return_7d_pct: float | None
    return_30d_pct: float | None
    return_all_time_pct: float | None
    max_drawdown_pct: float | None
    snapshot_count: int
    first_snapshot_at: datetime | None
    last_snapshot_at: datetime | None


def compute_performance_metrics(
    history: PerformanceHistory,
) -> PerformanceMetrics | None:
    """Derive return windows and max drawdown from stored snapshots."""
    snapshots = _sorted_snapshots(history.snapshots)
    if not snapshots:
        return None

    latest = snapshots[-1]
    current = latest.total_value
    now = _ensure_utc(latest.timestamp)

    return PerformanceMetrics(
        current_value=current,
        return_7d_pct=_return_pct(
            snapshots,
            current=current,
            since=now - timedelta(days=7),
        ),
        return_30d_pct=_return_pct(
            snapshots,
            current=current,
            since=now - timedelta(days=30),
        ),
        return_all_time_pct=_return_pct(
            snapshots,
            current=current,
            since=snapshots[0].timestamp,
        ),
        max_drawdown_pct=_max_drawdown_pct(snapshots),
        snapshot_count=len(snapshots),
        first_snapshot_at=snapshots[0].timestamp,
        last_snapshot_at=latest.timestamp,
    )


def _sorted_snapshots(
    snapshots: list[PortfolioPerformanceSnapshot],
) -> list[PortfolioPerformanceSnapshot]:
    return sorted(snapshots, key=lambda row: _ensure_utc(row.timestamp))


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _value_at_or_before(
    snapshots: list[PortfolioPerformanceSnapshot],
    target: datetime,
) -> float | None:
    target_utc = _ensure_utc(target)
    prior: PortfolioPerformanceSnapshot | None = None
    for item in snapshots:
        ts = _ensure_utc(item.timestamp)
        if ts <= target_utc:
            prior = item
        else:
            break
    return prior.total_value if prior is not None else None


def _return_pct(
    snapshots: list[PortfolioPerformanceSnapshot],
    *,
    current: float,
    since: datetime,
) -> float | None:
    baseline = _value_at_or_before(snapshots, since)
    if baseline is None or baseline <= 0:
        return None
    return ((current - baseline) / baseline) * 100.0


def _max_drawdown_pct(snapshots: list[PortfolioPerformanceSnapshot]) -> float | None:
    if not snapshots:
        return None

    peak = snapshots[0].total_value
    max_drawdown = 0.0
    for item in snapshots:
        value = item.total_value
        if value > peak:
            peak = value
        if peak > 0:
            drawdown = ((peak - value) / peak) * 100.0
            max_drawdown = max(max_drawdown, drawdown)
    return max_drawdown
