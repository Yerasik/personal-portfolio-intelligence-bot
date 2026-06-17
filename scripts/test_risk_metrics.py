#!/usr/bin/env python3
"""Smoke tests for historical risk metric helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.risk_metrics import compute_portfolio_historical_metrics, herfindahl_index


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

    print("Risk metrics checks passed.")


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
