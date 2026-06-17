"""Historical portfolio risk metrics from yfinance price history."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd

from collectors.market_data import _quiet_yfinance, portfolio_tickers
from storage.models import Portfolio

logger = logging.getLogger(__name__)

_TRADING_DAYS_PER_YEAR = 252
_MIN_RETURN_OBSERVATIONS = 10


@dataclass(frozen=True)
class PortfolioHistoricalMetrics:
    """Volatility and drawdown computed from aligned daily returns."""

    annual_volatility_pct: float | None
    max_drawdown_pct: float | None
    observation_days: int


def herfindahl_index(weights_pct: list[float]) -> float | None:
    """Return the Herfindahl-Hirschman index on decimal weights (0–1)."""
    if not weights_pct:
        return None
    total = sum(weights_pct)
    if total <= 0:
        return None
    decimals = [weight / total for weight in weights_pct]
    return sum(weight * weight for weight in decimals)


def fetch_close_history(ticker: str, *, lookback_months: int) -> pd.Series:
    """Download daily close prices for one ticker."""
    import yfinance as yf

    period = f"{max(lookback_months, 1)}mo"
    try:
        with _quiet_yfinance():
            history = yf.Ticker(ticker.strip().upper()).history(period=period)
    except Exception as exc:
        logger.warning("Price history fetch failed for %s: %s", ticker, exc)
        return pd.Series(dtype=float)

    if history is None or history.empty or "Close" not in history:
        return pd.Series(dtype=float)

    closes = history["Close"].astype(float)
    closes.index = pd.to_datetime(closes.index).tz_localize(None)
    return closes.sort_index()


def compute_portfolio_historical_metrics(
    weights_by_ticker: dict[str, float],
    *,
    lookback_months: int = 6,
) -> PortfolioHistoricalMetrics:
    """Compute annualized volatility and max drawdown from weighted daily returns."""
    normalized = _normalize_weights(weights_by_ticker)
    if not normalized:
        return PortfolioHistoricalMetrics(None, None, 0)

    closes_by_ticker: dict[str, pd.Series] = {}
    for ticker in normalized:
        series = fetch_close_history(ticker, lookback_months=lookback_months)
        if not series.empty:
            closes_by_ticker[ticker] = series

    if not closes_by_ticker:
        return PortfolioHistoricalMetrics(None, None, 0)

    price_frame = pd.DataFrame(closes_by_ticker).sort_index()
    returns = price_frame.pct_change()
    weight_series = pd.Series(normalized).reindex(returns.columns).fillna(0.0)
    if weight_series.sum() <= 0:
        return PortfolioHistoricalMetrics(None, None, 0)
    weight_series = weight_series / weight_series.sum()

    portfolio_returns = (returns * weight_series).sum(axis=1, min_count=1).dropna()
    if len(portfolio_returns) < _MIN_RETURN_OBSERVATIONS:
        return PortfolioHistoricalMetrics(None, None, len(portfolio_returns))

    daily_vol = float(portfolio_returns.std())
    annual_vol_pct = daily_vol * (_TRADING_DAYS_PER_YEAR**0.5) * 100.0

    wealth_index = (1.0 + portfolio_returns).cumprod()
    running_peak = wealth_index.cummax()
    drawdowns = (wealth_index / running_peak) - 1.0
    max_drawdown_pct = float(drawdowns.min() * 100.0)

    return PortfolioHistoricalMetrics(
        annual_volatility_pct=annual_vol_pct,
        max_drawdown_pct=max_drawdown_pct,
        observation_days=len(portfolio_returns),
    )


def weights_from_portfolio(
    portfolio: Portfolio,
    weights_pct_by_ticker: dict[str, float],
) -> dict[str, float]:
    """Map portfolio tickers to decimal weights."""
    symbols = portfolio_tickers(portfolio)
    raw = {symbol: weights_pct_by_ticker.get(symbol, 0.0) for symbol in symbols}
    return _normalize_weights(raw)


def _normalize_weights(weights_by_ticker: dict[str, float]) -> dict[str, float]:
    cleaned = {
        ticker.strip().upper(): max(0.0, weight)
        for ticker, weight in weights_by_ticker.items()
        if ticker.strip() and weight > 0
    }
    total = sum(cleaned.values())
    if total <= 0:
        return {}
    return {ticker: weight / total for ticker, weight in cleaned.items()}
