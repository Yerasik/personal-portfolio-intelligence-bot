#!/usr/bin/env python3
"""Smoke tests for performance chart aggregation."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.performance_chart import render_performance_chart_png
from analysis.performance_series import aggregate_performance_bars
from storage.models import PerformanceHistory, PortfolioPerformanceSnapshot


def _snapshot(*, at: datetime, value: float) -> PortfolioPerformanceSnapshot:
    return PortfolioPerformanceSnapshot(
        timestamp=at,
        total_value=value,
        total_cost=value * 0.9,
        daily_pnl_pct=0.0,
        positions={},
    )


def run_test() -> None:
    now = datetime(2026, 7, 2, 12, 0, tzinfo=UTC)
    snapshots: list[PortfolioPerformanceSnapshot] = []
    for day_offset in range(7):
        day = now - timedelta(days=6 - day_offset)
        for hour in (2, 8, 14):
            snapshots.append(
                _snapshot(
                    at=day.replace(hour=hour),
                    value=50_000 + day_offset * 500 + hour * 10,
                )
            )

    week_bars = aggregate_performance_bars(
        snapshots,
        period="week",
        timezone="Asia/Hong_Kong",
        now=now,
    )
    if len(week_bars) != 7:
        raise AssertionError(f"expected 7 daily bars, got {len(week_bars)}")
    if week_bars[0].close >= week_bars[-1].close:
        raise AssertionError("daily close series should trend upward in fixture")

    month_snapshots = [
        _snapshot(at=now - timedelta(days=28 - week * 7, hours=10), value=48_000 + week * 800)
        for week in range(5)
        for _ in range(3)
    ]
    month_bars = aggregate_performance_bars(
        month_snapshots,
        period="month",
        timezone="Asia/Hong_Kong",
        now=now,
    )
    if len(month_bars) < 2:
        raise AssertionError(f"expected weekly bars for month view, got {len(month_bars)}")

    chart = render_performance_chart_png(
        PerformanceHistory(snapshots=snapshots),
        period="week",
        timezone="Asia/Hong_Kong",
    )
    if chart is None or len(chart) < 100:
        raise AssertionError("expected aggregated candle chart PNG")

    print("test_performance_series: OK")


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
