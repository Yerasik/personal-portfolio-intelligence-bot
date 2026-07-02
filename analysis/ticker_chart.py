"""Candlestick chart rendering for a single ticker via mplfinance."""

from __future__ import annotations

import io
import logging
from typing import Literal

import pandas as pd

from analysis.indicator_rules import fetch_ohlcv_history

logger = logging.getLogger(__name__)

ChartPeriod = Literal["7d", "30d", "90d"]

_PERIOD_DAYS: dict[ChartPeriod, int] = {
    "7d": 7,
    "30d": 30,
    "90d": 90,
}

_PERIOD_MAV: dict[ChartPeriod, tuple[int, ...]] = {
    "7d": (),
    "30d": (20,),
    "90d": (20, 50),
}

_MIN_BARS = 2


def render_ticker_chart_png(ticker: str, *, period: ChartPeriod = "30d") -> bytes | None:
    """Fetch OHLCV and render a dark candlestick chart with volume and SMA overlays."""
    symbol = ticker.strip().upper()
    if not symbol:
        return None

    display_days = _PERIOD_DAYS[period]
    mav = _PERIOD_MAV[period]
    warmup = max(mav) if mav else 0
    lookback_days = display_days + warmup

    frame = fetch_ohlcv_history(symbol, lookback_days=lookback_days)
    if frame.empty or len(frame) < _MIN_BARS:
        logger.info("Insufficient OHLCV for chart: %s period=%s", symbol, period)
        return None

    plot_frame = frame.tail(display_days)
    if len(plot_frame) < _MIN_BARS:
        return None

    try:
        import matplotlib

        matplotlib.use("Agg")
        import mplfinance as mpf
    except ImportError:
        logger.warning("mplfinance is not installed; cannot render ticker chart")
        return None

    title = f"{symbol} — {period} price chart"
    buffer = io.BytesIO()
    plot_kwargs: dict = {
        "type": "candle",
        "style": "nightclouds",
        "volume": True,
        "title": title,
        "savefig": dict(
            fname=buffer,
            format="png",
            dpi=120,
            bbox_inches="tight",
            pad_inches=0.15,
        ),
    }
    if mav:
        plot_kwargs["mav"] = mav

    try:
        mpf.plot(plot_frame, **plot_kwargs)
    except Exception as exc:
        logger.warning("Chart render failed for %s: %s", symbol, exc)
        return None

    buffer.seek(0)
    return buffer.getvalue()
