#!/usr/bin/env python3
"""Smoke tests for RSI and MACD indicator alert helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.indicator_rules import evaluate_macd_signal, evaluate_rsi_signal
from analysis.rules import RulesEngine
from storage.models import AppConfig, BotState, NewsCache, Portfolio, Position


def _sample_ohlcv(rows: int = 30) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=rows, freq="B")
    return pd.DataFrame(
        {
            "Open": [100.0] * rows,
            "High": [101.0] * rows,
            "Low": [99.0] * rows,
            "Close": [100.0] * rows,
            "Volume": [1_000.0] * rows,
        },
        index=dates,
    )


def run_test() -> None:
    ohlcv = _sample_ohlcv()
    dates = ohlcv.index
    import pandas_ta as ta

    original_rsi = ta.rsi
    original_macd = ta.macd

    ta.rsi = lambda close, length=14: pd.Series([50.0] * (len(dates) - 2) + [68.0, 72.0], index=dates)
    try:
        rsi_signal = evaluate_rsi_signal(ohlcv)
    finally:
        ta.rsi = original_rsi

    if rsi_signal is None or rsi_signal.signal != "overbought":
        raise AssertionError(f"expected RSI overbought cross, got {rsi_signal}")

    macd_frame = pd.DataFrame(
        {
            "MACD_12_26_9": [-0.2, 0.3],
            "MACDs_12_26_9": [0.1, 0.1],
        },
        index=dates[-2:],
    )
    ta.macd = lambda close: macd_frame
    try:
        macd_signal = evaluate_macd_signal(ohlcv)
    finally:
        ta.macd = original_macd

    if macd_signal is None or macd_signal.signal != "bullish_cross":
        raise AssertionError(f"expected MACD bullish cross, got {macd_signal}")

    import analysis.indicator_rules as indicator_rules_module

    portfolio = Portfolio(positions=[Position(ticker="AAPL", shares=10)])
    engine = RulesEngine(app_config=AppConfig(), ticker_to_industry={})
    state = BotState()
    news_cache = NewsCache()

    original_fetch = indicator_rules_module.fetch_ohlcv_history
    original_rsi_fn = indicator_rules_module.evaluate_rsi_signal
    original_macd_fn = indicator_rules_module.evaluate_macd_signal

    def fake_fetch(ticker: str, *, lookback_days: int = 60) -> pd.DataFrame:
        if ticker == "AAPL":
            return ohlcv
        return pd.DataFrame()

    indicator_rules_module.fetch_ohlcv_history = fake_fetch
    indicator_rules_module.evaluate_rsi_signal = lambda frame: rsi_signal
    indicator_rules_module.evaluate_macd_signal = lambda frame: macd_signal
    try:
        alerts = engine.evaluate(portfolio, state, news_cache)
    finally:
        indicator_rules_module.fetch_ohlcv_history = original_fetch
        indicator_rules_module.evaluate_rsi_signal = original_rsi_fn
        indicator_rules_module.evaluate_macd_signal = original_macd_fn

    types = {alert.type for alert in alerts}
    if "rsi_alert" not in types or "macd_crossover" not in types:
        raise AssertionError(f"expected indicator alerts, got {types}")

    rsi_alert = next(alert for alert in alerts if alert.type == "rsi_alert")
    if rsi_alert.details.get("rsi") != 72.0:
        raise AssertionError(f"unexpected RSI detail: {rsi_alert.details}")

    print("Indicator rules checks passed.")


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
