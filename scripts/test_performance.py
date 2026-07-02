#!/usr/bin/env python3
"""Smoke tests for portfolio performance snapshots and metrics."""

from __future__ import annotations

import shutil
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.performance_chart import render_performance_chart_png
from analysis.performance_metrics import compute_performance_metrics
from bot.formatter import format_performance, format_performance_lines
from storage.models import (
    BotState,
    MarketQuote,
    PerformanceHistory,
    Portfolio,
    PortfolioPerformanceSnapshot,
    Position,
    PositionPerformancePoint,
)
from storage.paths import resolve_data_paths
from storage.performance_ops import build_portfolio_snapshot, save_portfolio_snapshot
from storage.repository import DataRepository


def _snapshot(
    *,
    days_ago: float,
    total_value: float,
) -> PortfolioPerformanceSnapshot:
    return PortfolioPerformanceSnapshot(
        timestamp=datetime.now(tz=UTC) - timedelta(days=days_ago),
        total_value=total_value,
        total_cost=total_value * 0.9,
        daily_pnl_pct=0.0,
        positions={
            "AAPL": PositionPerformancePoint(price=100.0, value=total_value),
        },
    )


def run_test() -> None:
    history = PerformanceHistory(
        snapshots=[
            _snapshot(days_ago=45, total_value=10_000.0),
            _snapshot(days_ago=20, total_value=11_000.0),
            _snapshot(days_ago=5, total_value=10_500.0),
            _snapshot(days_ago=0, total_value=12_000.0),
        ]
    )
    metrics = compute_performance_metrics(history)
    if metrics is None:
        raise AssertionError("expected metrics from snapshots")
    if metrics.return_7d_pct is None or metrics.return_30d_pct is None:
        raise AssertionError("expected 7d and 30d returns")
    if metrics.return_all_time_pct is None or metrics.return_all_time_pct <= 0:
        raise AssertionError(f"unexpected all-time return: {metrics.return_all_time_pct}")
    if metrics.max_drawdown_pct is None or metrics.max_drawdown_pct <= 0:
        raise AssertionError(f"expected positive drawdown, got {metrics.max_drawdown_pct}")

    lines = format_performance_lines(metrics, lang="en")
    if len(lines) != 5:
        raise AssertionError(f"expected 5 performance lines, got {len(lines)}")
    report = format_performance(metrics, lang="en")
    if "7-day return" not in report:
        raise AssertionError("formatted report missing 7-day return")

    chart = render_performance_chart_png(history, period="month", timezone="Asia/Hong_Kong")
    if chart is None or len(chart) < 100:
        raise AssertionError("expected non-trivial PNG chart bytes")

    temp_dir = Path(tempfile.mkdtemp(prefix="performance-test-"))
    try:
        for name in (
            "config.json",
            "portfolio.json",
            "state.json",
            "news_cache.json",
            "ticker_industries.json",
            "ticker_metadata.json",
            "ticker_strategies.json",
            "signals.json",
            "users.json",
        ):
            shutil.copy(ROOT / "data" / "examples" / name, temp_dir / name)

        paths = resolve_data_paths(temp_dir)
        repository = DataRepository(paths)
        portfolio = Portfolio(
            positions=[Position(ticker="AAPL", shares=10, cost_basis=150.0)],
            cash=1_000.0,
        )
        repository.save_portfolio(portfolio)
        state = BotState(
            latest_prices={
                "AAPL": MarketQuote(
                    ticker="AAPL",
                    price=180.0,
                    change_pct=1.0,
                    currency="USD",
                    fetched_at=datetime.now(tz=UTC),
                )
            },
            last_market_fetch_at=datetime.now(tz=UTC),
        )
        repository.save_state(state)

        snapshot = build_portfolio_snapshot(portfolio, state)
        if snapshot is None or snapshot.total_value <= 0:
            raise AssertionError("expected snapshot from portfolio and quotes")

        saved = save_portfolio_snapshot(repository)
        if saved is None:
            raise AssertionError("save_portfolio_snapshot should append a record")

        loaded = repository.load_performance_history()
        if len(loaded.snapshots) != 1:
            raise AssertionError(f"expected 1 snapshot, got {len(loaded.snapshots)}")
        row = loaded.snapshots[0]
        if "AAPL" not in row.positions:
            raise AssertionError("snapshot should include AAPL position")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    print("test_performance: OK")


if __name__ == "__main__":
    run_test()
