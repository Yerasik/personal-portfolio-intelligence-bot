#!/usr/bin/env python3
"""Smoke tests for /chart argument parsing and chart rendering."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import analysis.ticker_chart as ticker_chart_module
from analysis.ticker_chart import render_ticker_chart_png
from bot.chart_args import parse_chart_args


def _sample_ohlcv(rows: int = 90) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=rows, freq="B")
    close = pd.Series(range(100, 100 + rows), index=dates, dtype=float)
    return pd.DataFrame(
        {
            "Open": close - 0.5,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": [10_000.0 + index for index in range(rows)],
        },
        index=dates,
    )


def run_test() -> None:
    parsed, err = parse_chart_args(["AAPL"])
    if err is not None or parsed is None or parsed.period != "30d":
        raise AssertionError(f"default period parse failed: {parsed}, {err}")

    parsed, err = parse_chart_args(["NVDA", "90d"])
    if err is not None or parsed is None or parsed.period != "90d":
        raise AssertionError(f"90d parse failed: {parsed}, {err}")

    _, err = parse_chart_args(["AAPL", "1y"])
    if err != "chart_invalid_period":
        raise AssertionError(f"expected invalid period error, got {err!r}")

    _, err = parse_chart_args([])
    if err != "chart_usage":
        raise AssertionError(f"expected usage error, got {err!r}")

    original_fetch = ticker_chart_module.fetch_ohlcv_history
    sample = _sample_ohlcv()

    def _mock_fetch(ticker: str, *, lookback_days: int = 60) -> pd.DataFrame:
        if ticker == "AAPL":
            return sample.tail(max(lookback_days, 2))
        return pd.DataFrame()

    ticker_chart_module.fetch_ohlcv_history = _mock_fetch
    try:
        png = render_ticker_chart_png("AAPL", period="30d")
        if png is None or len(png) < 1000:
            raise AssertionError("expected non-trivial PNG bytes for AAPL")
        if png[:8] != b"\x89PNG\r\n\x1a\n":
            raise AssertionError("output should be a PNG file")

        if render_ticker_chart_png("BAD", period="7d") is not None:
            raise AssertionError("invalid ticker should return None")
    finally:
        ticker_chart_module.fetch_ohlcv_history = original_fetch

    print("test_ticker_chart: OK")


if __name__ == "__main__":
    run_test()
