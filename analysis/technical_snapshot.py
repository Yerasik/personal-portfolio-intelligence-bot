"""On-demand technical analysis snapshot for a single ticker."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import pandas as pd

from analysis.indicator_rules import fetch_ohlcv_history

logger = logging.getLogger(__name__)

_TA_LOOKBACK_DAYS = 90
_MIN_OHLCV_ROWS = 55
_RSI_LENGTH = 14
_RSI_OVERBOUGHT = 70.0
_RSI_OVERSOLD = 30.0
_SMA_FAST = 20
_SMA_SLOW = 50

RsiLabel = Literal["overbought", "oversold", "neutral"]
MacdStatus = Literal[
    "bullish_cross",
    "bearish_cross",
    "bullish",
    "bearish",
    "neutral",
]
SmaStatus = Literal["golden_cross", "death_cross", "bullish", "bearish", "neutral"]
BollingerStatus = Literal["above_upper", "below_lower", "inside"]


@dataclass(frozen=True)
class TechnicalSnapshot:
    """Computed indicator readings for one ticker."""

    ticker: str
    close_price: float
    rsi_value: float
    rsi_label: RsiLabel
    macd_status: MacdStatus
    sma_status: SmaStatus
    bollinger_status: BollingerStatus


def build_technical_snapshot(ticker: str) -> TechnicalSnapshot | None:
    """Fetch 90 days of OHLCV and compute RSI, MACD, SMA, and Bollinger readings."""
    symbol = ticker.strip().upper()
    if not symbol:
        return None

    ohlcv = fetch_ohlcv_history(symbol, lookback_days=_TA_LOOKBACK_DAYS)
    if ohlcv.empty or len(ohlcv) < _MIN_OHLCV_ROWS:
        logger.info("Insufficient OHLCV history for TA snapshot: %s", symbol)
        return None

    try:
        import pandas_ta as ta
    except ImportError:
        logger.warning("pandas_ta is not installed; cannot build TA snapshot")
        return None

    close = ohlcv["Close"]
    rsi_series = ta.rsi(close, length=_RSI_LENGTH)
    if rsi_series is None or rsi_series.dropna().empty:
        return None
    rsi_value = float(rsi_series.iloc[-1])
    if pd.isna(rsi_value):
        return None

    macd_status = _macd_status(ta.macd(close))
    sma_status = _sma_status(ta.sma(close, length=_SMA_FAST), ta.sma(close, length=_SMA_SLOW))
    bollinger_status = _bollinger_status(close.iloc[-1], ta.bbands(close, length=20))

    return TechnicalSnapshot(
        ticker=symbol,
        close_price=float(close.iloc[-1]),
        rsi_value=rsi_value,
        rsi_label=_rsi_label(rsi_value),
        macd_status=macd_status,
        sma_status=sma_status,
        bollinger_status=bollinger_status,
    )


def _rsi_label(value: float) -> RsiLabel:
    if value >= _RSI_OVERBOUGHT:
        return "overbought"
    if value <= _RSI_OVERSOLD:
        return "oversold"
    return "neutral"


def _macd_status(macd_frame: pd.DataFrame | None) -> MacdStatus:
    if macd_frame is None or macd_frame.empty:
        return "neutral"

    macd_cols = [column for column in macd_frame.columns if column.startswith("MACD_")]
    signal_cols = [column for column in macd_frame.columns if column.startswith("MACDs_")]
    if not macd_cols or not signal_cols:
        return "neutral"

    aligned = pd.concat(
        [macd_frame[macd_cols[0]], macd_frame[signal_cols[0]]],
        axis=1,
        join="inner",
    ).dropna()
    if len(aligned) < 2:
        return "neutral"

    prev_macd = float(aligned.iloc[-2, 0])
    curr_macd = float(aligned.iloc[-1, 0])
    prev_signal = float(aligned.iloc[-2, 1])
    curr_signal = float(aligned.iloc[-1, 1])

    if prev_macd <= prev_signal < curr_macd:
        return "bullish_cross"
    if prev_macd >= prev_signal > curr_macd:
        return "bearish_cross"
    if curr_macd > curr_signal:
        return "bullish"
    if curr_macd < curr_signal:
        return "bearish"
    return "neutral"


def _sma_status(
    sma_fast: pd.Series | None,
    sma_slow: pd.Series | None,
) -> SmaStatus:
    if sma_fast is None or sma_slow is None:
        return "neutral"

    aligned = pd.concat([sma_fast, sma_slow], axis=1, join="inner").dropna()
    if len(aligned) < 2:
        return "neutral"

    prev_fast = float(aligned.iloc[-2, 0])
    curr_fast = float(aligned.iloc[-1, 0])
    prev_slow = float(aligned.iloc[-2, 1])
    curr_slow = float(aligned.iloc[-1, 1])

    if prev_fast <= prev_slow < curr_fast:
        return "golden_cross"
    if prev_fast >= prev_slow > curr_fast:
        return "death_cross"
    if curr_fast > curr_slow:
        return "bullish"
    if curr_fast < curr_slow:
        return "bearish"
    return "neutral"


def _bollinger_status(
    last_close: float,
    bands: pd.DataFrame | None,
) -> BollingerStatus:
    if bands is None or bands.empty:
        return "inside"

    lower_cols = [column for column in bands.columns if column.startswith("BBL_")]
    upper_cols = [column for column in bands.columns if column.startswith("BBU_")]
    if not lower_cols or not upper_cols:
        return "inside"

    lower = float(bands[lower_cols[0]].iloc[-1])
    upper = float(bands[upper_cols[0]].iloc[-1])
    if pd.isna(lower) or pd.isna(upper):
        return "inside"
    if last_close > upper:
        return "above_upper"
    if last_close < lower:
        return "below_lower"
    return "inside"
