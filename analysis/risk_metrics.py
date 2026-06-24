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
_DEFAULT_RISK_FREE_RATE_ANNUAL = 0.045
_DEFAULT_LOOKBACK_DAYS = 90


@dataclass(frozen=True)
class RiskMetricsReport:
    """On-demand portfolio risk statistics vs a benchmark."""

    sharpe_ratio: float | None
    max_drawdown_pct: float | None
    portfolio_return_pct: float | None
    benchmark_return_pct: float | None
    alpha_pct: float | None
    benchmark_ticker: str
    observation_days: int


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
    return _fetch_close_history(ticker, period=f"{max(lookback_months, 1)}mo")


def fetch_close_history_days(ticker: str, *, lookback_days: int = _DEFAULT_LOOKBACK_DAYS) -> pd.Series:
    """Download daily close prices for the last N calendar days."""
    return _fetch_close_history(ticker, period=f"{max(lookback_days, 1)}d")


def _fetch_close_history(ticker: str, *, period: str) -> pd.Series:
    """Download daily close prices for one ticker and period string."""
    import yfinance as yf

    symbol = ticker.strip().upper()
    try:
        with _quiet_yfinance():
            history = yf.Ticker(symbol).history(period=period)
    except Exception as exc:
        logger.warning("Price history fetch failed for %s: %s", symbol, exc)
        return pd.Series(dtype=float)

    if history is None or history.empty or "Close" not in history:
        return pd.Series(dtype=float)

    closes = history["Close"].astype(float)
    closes.index = pd.to_datetime(closes.index).tz_localize(None)
    return closes.sort_index()


def compute_risk_metrics_report(
    weights_by_ticker: dict[str, float],
    *,
    benchmark_ticker: str = "SPY",
    risk_free_rate_annual: float = _DEFAULT_RISK_FREE_RATE_ANNUAL,
    lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
) -> RiskMetricsReport | None:
    """Compute Sharpe, drawdown, returns, and alpha vs a benchmark from yfinance history."""
    normalized = _normalize_weights(weights_by_ticker)
    benchmark = benchmark_ticker.strip().upper() or "SPY"
    if not normalized:
        return None

    closes_by_ticker: dict[str, pd.Series] = {}
    for ticker in normalized:
        series = fetch_close_history_days(ticker, lookback_days=lookback_days)
        if not series.empty:
            closes_by_ticker[ticker] = series

    if not closes_by_ticker:
        return None

    benchmark_closes = fetch_close_history_days(benchmark, lookback_days=lookback_days)
    portfolio_returns = _weighted_daily_returns(closes_by_ticker, normalized)
    if portfolio_returns is None:
        return None

    benchmark_returns = benchmark_closes.pct_change().dropna()
    aligned_benchmark = benchmark_returns.reindex(portfolio_returns.index).dropna()
    aligned_portfolio = portfolio_returns.reindex(aligned_benchmark.index).dropna()
    if len(aligned_portfolio) < _MIN_RETURN_OBSERVATIONS:
        return None

    sharpe_ratio = _annualized_sharpe(aligned_portfolio, risk_free_rate_annual)
    max_drawdown_pct = _max_drawdown_pct(aligned_portfolio)
    portfolio_return_pct = _total_return_pct(aligned_portfolio)
    benchmark_return_pct = (
        _total_return_pct(aligned_benchmark) if not aligned_benchmark.empty else None
    )
    alpha_pct = (
        portfolio_return_pct - benchmark_return_pct
        if portfolio_return_pct is not None and benchmark_return_pct is not None
        else None
    )

    return RiskMetricsReport(
        sharpe_ratio=sharpe_ratio,
        max_drawdown_pct=max_drawdown_pct,
        portfolio_return_pct=portfolio_return_pct,
        benchmark_return_pct=benchmark_return_pct,
        alpha_pct=alpha_pct,
        benchmark_ticker=benchmark,
        observation_days=len(aligned_portfolio),
    )


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

    portfolio_returns = _weighted_daily_returns(closes_by_ticker, normalized)
    if portfolio_returns is None:
        return PortfolioHistoricalMetrics(None, None, 0)

    daily_vol = float(portfolio_returns.std())
    annual_vol_pct = daily_vol * (_TRADING_DAYS_PER_YEAR**0.5) * 100.0
    max_drawdown_pct = _max_drawdown_pct(portfolio_returns)

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


def _weighted_daily_returns(
    closes_by_ticker: dict[str, pd.Series],
    normalized_weights: dict[str, float],
) -> pd.Series | None:
    price_frame = pd.DataFrame(closes_by_ticker).sort_index()
    returns = price_frame.pct_change()
    weight_series = pd.Series(normalized_weights).reindex(returns.columns).fillna(0.0)
    if weight_series.sum() <= 0:
        return None
    weight_series = weight_series / weight_series.sum()

    portfolio_returns = (returns * weight_series).sum(axis=1, min_count=1).dropna()
    if len(portfolio_returns) < _MIN_RETURN_OBSERVATIONS:
        return None
    return portfolio_returns


def _annualized_sharpe(
    daily_returns: pd.Series,
    risk_free_rate_annual: float,
) -> float | None:
    daily_std = float(daily_returns.std())
    if daily_std <= 0:
        return None
    rf_daily = risk_free_rate_annual / _TRADING_DAYS_PER_YEAR
    excess_mean = float(daily_returns.mean() - rf_daily)
    return excess_mean / daily_std * (_TRADING_DAYS_PER_YEAR**0.5)


def _total_return_pct(daily_returns: pd.Series) -> float | None:
    if daily_returns.empty:
        return None
    wealth_index = (1.0 + daily_returns).cumprod()
    return float((wealth_index.iloc[-1] - 1.0) * 100.0)


def _max_drawdown_pct(daily_returns: pd.Series) -> float | None:
    if daily_returns.empty:
        return None
    wealth_index = (1.0 + daily_returns).cumprod()
    running_peak = wealth_index.cummax()
    drawdowns = (wealth_index / running_peak) - 1.0
    return float(drawdowns.min() * 100.0)
