"""Market price and quote collection."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

import yfinance as yf

from collectors.base import BaseCollector, CollectorContext, CollectorResult
from storage.models import MarketQuote, Portfolio
from storage.repository import DataRepository

logger = logging.getLogger(__name__)


def portfolio_tickers(portfolio: Portfolio) -> list[str]:
    """Return unique tickers from portfolio positions, preserving order."""
    seen: set[str] = set()
    tickers: list[str] = []
    for position in portfolio.positions:
        symbol = position.ticker.strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        tickers.append(symbol)
    return tickers


def _coerce_float(value: object | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: object | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _pick_str(source: dict[str, object], *keys: str) -> str:
    for key in keys:
        raw = source.get(key)
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    return ""


def fetch_quote(ticker: str, fetched_at: datetime | None = None) -> MarketQuote:
    """Fetch a normalized quote for one ticker via yfinance."""
    symbol = ticker.strip().upper()
    if not symbol:
        raise ValueError("Ticker symbol is empty")

    when = fetched_at or datetime.now(tz=UTC)
    stock = yf.Ticker(symbol)
    info: dict[str, object] = {}

    try:
        raw_info = stock.info
        if isinstance(raw_info, dict):
            info = raw_info
    except Exception as exc:
        logger.debug("yfinance info lookup failed for %s: %s", symbol, exc)

    price: float | None = None
    change_pct: float | None = None
    volume: int | None = None

    try:
        fast = stock.fast_info
        price = _coerce_float(
            getattr(fast, "last_price", None)
            or getattr(fast, "regular_market_price", None)
        )
        previous_close = _coerce_float(
            getattr(fast, "previous_close", None)
            or getattr(fast, "regular_market_previous_close", None)
        )
        volume = _coerce_int(
            getattr(fast, "last_volume", None)
            or getattr(fast, "three_month_average_volume", None)
        )
        if price is not None and previous_close not in (None, 0):
            change_pct = ((price - previous_close) / previous_close) * 100
    except Exception as exc:
        logger.debug("yfinance fast_info lookup failed for %s: %s", symbol, exc)

    if price is None:
        price = _coerce_float(
            info.get("currentPrice") or info.get("regularMarketPrice")
        )
    if change_pct is None:
        change_pct = _coerce_float(info.get("regularMarketChangePercent"))
    if volume is None:
        volume = _coerce_int(info.get("volume") or info.get("regularMarketVolume"))

    if price is None:
        history = stock.history(period="5d")
        if not history.empty:
            price = _coerce_float(history["Close"].iloc[-1])
            volume = _coerce_int(history["Volume"].iloc[-1])
            if len(history) >= 2:
                previous = _coerce_float(history["Close"].iloc[-2])
                if price is not None and previous not in (None, 0):
                    change_pct = ((price - previous) / previous) * 100

    if price is None:
        raise ValueError(f"No price data returned for {symbol}")

    return MarketQuote(
        ticker=symbol,
        price=price,
        change_pct=change_pct,
        volume=volume,
        company_name=_pick_str(info, "shortName", "longName"),
        sector=_pick_str(info, "sector"),
        industry=_pick_str(info, "industry"),
        currency=_pick_str(info, "currency"),
        fetched_at=when,
    )


@dataclass
class MarketDataBatchResult:
    """Outcome of a multi-ticker market data fetch."""

    quotes: dict[str, MarketQuote] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)
    fetched_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))

    @property
    def success_count(self) -> int:
        return len(self.quotes)

    @property
    def failure_count(self) -> int:
        return len(self.failures)


class MarketDataService:
    """Fetch portfolio quotes and persist them into state.json."""

    def fetch_batch(self, tickers: list[str]) -> MarketDataBatchResult:
        """Fetch quotes for each ticker, recording per-ticker failures."""
        fetched_at = datetime.now(tz=UTC)
        result = MarketDataBatchResult(fetched_at=fetched_at)

        if not tickers:
            logger.info("No portfolio tickers to fetch")
            return result

        logger.info("Fetching market data for %d ticker(s): %s", len(tickers), tickers)

        for symbol in tickers:
            try:
                quote = fetch_quote(symbol, fetched_at=fetched_at)
            except Exception as exc:
                message = str(exc) or exc.__class__.__name__
                result.failures[symbol] = message
                logger.warning("Market fetch failed for %s: %s", symbol, message)
                continue

            result.quotes[symbol] = quote
            change_text = (
                f"{quote.change_pct:+.2f}%"
                if quote.change_pct is not None
                else "n/a"
            )
            logger.info(
                "Fetched %s price=%.4f change=%s volume=%s",
                symbol,
                quote.price or 0,
                change_text,
                quote.volume if quote.volume is not None else "n/a",
            )

        logger.info(
            "Market fetch complete: %d succeeded, %d failed",
            result.success_count,
            result.failure_count,
        )
        return result

    def run(self, repository: DataRepository, portfolio: Portfolio) -> MarketDataBatchResult:
        """Fetch portfolio quotes and update state.json."""
        tickers = portfolio_tickers(portfolio)
        batch = self.fetch_batch(tickers)

        state = repository.load_state()
        state.latest_prices.update(batch.quotes)
        state.last_market_fetch_at = batch.fetched_at
        repository.save_state(state)

        logger.info(
            "Updated state.json with %d quote(s); last_market_fetch_at=%s",
            batch.success_count,
            batch.fetched_at.isoformat(),
        )
        return batch


class MarketDataCollector(BaseCollector):
    """Scheduled collector that refreshes portfolio market quotes."""

    name = "market_data"

    def __init__(self, service: MarketDataService | None = None) -> None:
        self._service = service or MarketDataService()

    def run(self, context: CollectorContext) -> CollectorResult:
        portfolio = context.repository.load_portfolio()
        tickers = portfolio_tickers(portfolio)

        if not tickers:
            return CollectorResult(
                name=self.name,
                success=True,
                message="no portfolio tickers to fetch",
            )

        batch = self._service.run(context.repository, portfolio)
        success = batch.success_count > 0 or batch.failure_count == 0

        if batch.failure_count and batch.success_count:
            message = (
                f"fetched {batch.success_count}/{len(tickers)} tickers "
                f"({batch.failure_count} failed)"
            )
        elif batch.failure_count:
            message = f"all {batch.failure_count} ticker fetch(es) failed"
        else:
            message = f"fetched {batch.success_count} ticker(s)"

        return CollectorResult(
            name=self.name,
            success=success,
            message=message,
            finished_at=batch.fetched_at,
        )
