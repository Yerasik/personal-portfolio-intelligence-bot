#!/usr/bin/env python3
"""Smoke tests for historical risk metric helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.risk_metrics import (
    compute_portfolio_historical_metrics,
    compute_risk_metrics_report,
    herfindahl_index,
)
from bot.formatter import format_risk_metrics


def run_test() -> None:
    weights = {"AAA": 60.0, "BBB": 40.0}
    dates = pd.date_range("2026-01-01", periods=30, freq="B")
    stable = pd.Series([100 + index * 0.1 for index in range(len(dates))], index=dates)
    volatile = pd.Series(
        [50 + (5 if index % 2 == 0 else -5) for index in range(len(dates))],
        index=dates,
    )

    import analysis.risk_metrics as risk_metrics_module

    original_fetch = risk_metrics_module.fetch_close_history

    def fake_fetch(ticker: str, *, lookback_months: int) -> pd.Series:
        if ticker == "AAA":
            return stable
        if ticker == "BBB":
            return volatile
        return pd.Series(dtype=float)

    risk_metrics_module.fetch_close_history = fake_fetch
    try:
        metrics = compute_portfolio_historical_metrics(weights, lookback_months=3)
    finally:
        risk_metrics_module.fetch_close_history = original_fetch

    if metrics.annual_volatility_pct is None:
        raise AssertionError("expected annual volatility from synthetic history")
    if metrics.max_drawdown_pct is None:
        raise AssertionError("expected max drawdown from synthetic history")
    if metrics.annual_volatility_pct <= 0:
        raise AssertionError("volatility should be positive")
    if metrics.max_drawdown_pct >= 0:
        raise AssertionError("drawdown should be negative")

    hhi = herfindahl_index([100.0])
    if hhi != 1.0:
        raise AssertionError(f"single-name portfolio HHI should be 1.0, got {hhi}")

    dates = pd.date_range("2026-01-01", periods=40, freq="B")
    portfolio_series = pd.Series([100 + index * 0.5 for index in range(len(dates))], index=dates)
    benchmark_series = pd.Series([200 + index * 0.2 for index in range(len(dates))], index=dates)

    original_fetch_days = risk_metrics_module.fetch_close_history_days

    def fake_fetch_days(ticker: str, *, lookback_days: int = 90) -> pd.Series:
        if ticker == "AAA":
            return portfolio_series
        if ticker == "SPY":
            return benchmark_series
        return pd.Series(dtype=float)

    risk_metrics_module.fetch_close_history_days = fake_fetch_days
    try:
        report = compute_risk_metrics_report(
            {"AAA": 100.0},
            benchmark_ticker="SPY",
        )
    finally:
        risk_metrics_module.fetch_close_history_days = original_fetch_days

    if report is None:
        raise AssertionError("expected risk metrics report from synthetic history")
    if report.sharpe_ratio is None:
        raise AssertionError("expected Sharpe ratio")
    if report.max_drawdown_pct is None:
        raise AssertionError("expected max drawdown")
    if report.portfolio_return_pct is None or report.benchmark_return_pct is None:
        raise AssertionError("expected portfolio and benchmark returns")
    if report.alpha_pct is None:
        raise AssertionError("expected alpha")
    if abs(report.alpha_pct - (report.portfolio_return_pct - report.benchmark_return_pct)) > 1e-6:
        raise AssertionError("alpha should equal excess return over benchmark")

    formatted = format_risk_metrics(report, lang="en")
    if "Sharpe ratio" not in formatted or "Alpha vs benchmark" not in formatted:
        raise AssertionError(f"unexpected formatted risk metrics: {formatted!r}")

    print("Risk metrics checks passed.")


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
