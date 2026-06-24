"""Technical indicator alerts using pandas_ta and yfinance OHLCV history."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd

from collectors.market_data import _quiet_yfinance

logger = logging.getLogger(__name__)

_LOOKBACK_DAYS = 60
_RSI_LENGTH = 14
_RSI_OVERBOUGHT = 70.0
_RSI_OVERSOLD = 30.0
_MIN_OHLCV_ROWS = 20


@dataclass(frozen=True)
class IndicatorSignal:
    """A detected RSI or MACD crossover event."""

    signal: str
    indicator_value: float
    secondary_value: float | None = None


def fetch_ohlcv_history(ticker: str, *, lookback_days: int = _LOOKBACK_DAYS) -> pd.DataFrame:
    """Download daily OHLCV bars for one ticker."""
    import yfinance as yf

    symbol = ticker.strip().upper()
    period = f"{max(lookback_days, 1)}d"
    try:
        with _quiet_yfinance():
            history = yf.Ticker(symbol).history(period=period)
    except Exception as exc:
        logger.warning("OHLCV fetch failed for %s: %s", symbol, exc)
        return pd.DataFrame()

    if history is None or history.empty:
        return pd.DataFrame()

    required = ("Open", "High", "Low", "Close", "Volume")
    if not all(column in history.columns for column in required):
        return pd.DataFrame()

    frame = history[list(required)].astype(float)
    frame.index = pd.to_datetime(frame.index).tz_localize(None)
    return frame.sort_index()


def evaluate_rsi_signal(ohlcv: pd.DataFrame) -> IndicatorSignal | None:
    """Return overbought/oversold when RSI(14) crosses 70 or 30."""
    if len(ohlcv) < _MIN_OHLCV_ROWS:
        return None

    import pandas_ta as ta

    rsi = ta.rsi(ohlcv["Close"], length=_RSI_LENGTH)
    if rsi is None or rsi.dropna().shape[0] < 2:
        return None

    previous = float(rsi.iloc[-2])
    current = float(rsi.iloc[-1])
    if pd.isna(previous) or pd.isna(current):
        return None

    if previous <= _RSI_OVERBOUGHT < current:
        return IndicatorSignal(signal="overbought", indicator_value=current)
    if previous >= _RSI_OVERSOLD > current:
        return IndicatorSignal(signal="oversold", indicator_value=current)
    return None


def evaluate_macd_signal(ohlcv: pd.DataFrame) -> IndicatorSignal | None:
    """Return bullish/bearish when the MACD line crosses the signal line."""
    if len(ohlcv) < _MIN_OHLCV_ROWS:
        return None

    import pandas_ta as ta

    macd = ta.macd(ohlcv["Close"])
    if macd is None or macd.empty:
        return None

    macd_cols = [column for column in macd.columns if column.startswith("MACD_")]
    signal_cols = [column for column in macd.columns if column.startswith("MACDs_")]
    if not macd_cols or not signal_cols:
        return None

    macd_line = macd[macd_cols[0]].dropna()
    signal_line = macd[signal_cols[0]].dropna()
    aligned = pd.concat([macd_line, signal_line], axis=1, join="inner").dropna()
    if len(aligned) < 2:
        return None

    prev_macd = float(aligned.iloc[-2, 0])
    curr_macd = float(aligned.iloc[-1, 0])
    prev_signal = float(aligned.iloc[-2, 1])
    curr_signal = float(aligned.iloc[-1, 1])

    if prev_macd <= prev_signal < curr_macd:
        return IndicatorSignal(
            signal="bullish_cross",
            indicator_value=curr_macd,
            secondary_value=curr_signal,
        )
    if prev_macd >= prev_signal > curr_macd:
        return IndicatorSignal(
            signal="bearish_cross",
            indicator_value=curr_macd,
            secondary_value=curr_signal,
        )
    return None
