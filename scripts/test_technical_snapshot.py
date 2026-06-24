#!/usr/bin/env python3
"""Smoke tests for /ta technical snapshot helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import analysis.technical_snapshot as technical_snapshot_module
from analysis.technical_snapshot import TechnicalSnapshot, build_technical_snapshot
from bot.formatter import format_technical_snapshot
from bot.markdown_v2 import escape_markdown_v2


def _sample_ohlcv(rows: int = 60) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=rows, freq="B")
    close = pd.Series([100.0] * rows, index=dates, dtype=float)
    return pd.DataFrame(
        {
            "Open": close - 0.5,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": [1_000.0] * rows,
        },
        index=dates,
    )


def run_test() -> None:
    assert escape_markdown_v2("AAPL (14.5%)") == "AAPL \\(14\\.5%\\)"

    ohlcv = _sample_ohlcv()
    dates = ohlcv.index
    import pandas_ta as ta

    original_fetch = technical_snapshot_module.fetch_ohlcv_history
    original_rsi = ta.rsi
    original_macd = ta.macd
    original_sma = ta.sma
    original_bbands = ta.bbands

    rsi_series = pd.Series([50.0] * (len(dates) - 1) + [72.0], index=dates)
    macd_frame = pd.DataFrame(
        {
            "MACD_12_26_9": [0.1, 0.3],
            "MACDs_12_26_9": [0.2, 0.2],
        },
        index=dates[-2:],
    )
    sma_fast = pd.Series([99.5, 101.0], index=dates[-2:])
    sma_slow = pd.Series([100.0, 100.5], index=dates[-2:])
    bb_frame = pd.DataFrame(
        {
            "BBL_20_2.0": [95.0, 96.0],
            "BBM_20_2.0": [100.0, 101.0],
            "BBU_20_2.0": [105.0, 106.0],
        },
        index=dates[-2:],
    )

    technical_snapshot_module.fetch_ohlcv_history = (
        lambda ticker, *, lookback_days=90: ohlcv if ticker == "AAPL" else pd.DataFrame()
    )
    ta.rsi = lambda close, length=14: rsi_series
    ta.macd = lambda close: macd_frame
    ta.sma = lambda close, length=20: sma_fast if length == 20 else sma_slow
    ta.bbands = lambda close, length=20: bb_frame

    try:
        snapshot = build_technical_snapshot("AAPL")
    finally:
        technical_snapshot_module.fetch_ohlcv_history = original_fetch
        ta.rsi = original_rsi
        ta.macd = original_macd
        ta.sma = original_sma
        ta.bbands = original_bbands

    if snapshot is None:
        raise AssertionError("expected technical snapshot")
    if snapshot.rsi_label != "overbought":
        raise AssertionError(f"expected overbought RSI, got {snapshot.rsi_label}")
    if snapshot.macd_status != "bullish_cross":
        raise AssertionError(f"expected bullish MACD cross, got {snapshot.macd_status}")
    if snapshot.sma_status != "golden_cross":
        raise AssertionError(f"expected golden cross, got {snapshot.sma_status}")
    if snapshot.bollinger_status != "inside":
        raise AssertionError(f"expected inside bands, got {snapshot.bollinger_status}")

    formatted = format_technical_snapshot(snapshot, lang="en")
    if "RSI\\(14\\)" not in formatted or "bullish crossover" not in formatted:
        raise AssertionError(f"unexpected markdown output: {formatted!r}")

    technical_snapshot_module.fetch_ohlcv_history = lambda ticker, **kwargs: pd.DataFrame()
    if build_technical_snapshot("BAD") is not None:
        raise AssertionError("empty history should return None")

    print("test_technical_snapshot: OK")


if __name__ == "__main__":
    run_test()
