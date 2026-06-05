"""Market price and quote collection.

Uses yfinance to fetch daily bars for portfolio tickers and writes results to
state.json → latest_prices. Failures for one ticker do not block others.
"""

from __future__ import annotations

import logging
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

import yfinance as yf

from collectors.base import BaseCollector, CollectorContext, CollectorResult
from storage.models import MarketQuote, Portfolio
from storage.repository import DataRepository

logger = logging.getLogger(__name__)

_YFINANCE_LOGGERS = (
    "yfinance",
    "urllib3",
    "urllib3.connectionpool",
    "peewee",
)


@contextmanager
def _quiet_yfinance() -> Iterator[None]:
    """Suppress noisy yfinance, HTTP client, and pandas warnings during API calls."""
    previous_levels = {
        name: logging.getLogger(name).level for name in _YFINANCE_LOGGERS
    }
    try:
        for name in _YFINANCE_LOGGERS:
            logging.getLogger(name).setLevel(logging.CRITICAL)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            yield
    finally:
        for name, level in previous_levels.items():
            logging.getLogger(name).setLevel(level)


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
    """Safely convert yfinance values to float; return None on bad data."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: object | None) -> int | None:
    """Safely convert yfinance volume values to int."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _pick_str(source: dict[str, object], *keys: str) -> str:
    """Return the first non-empty string value from a yfinance info dict."""
    for key in keys:
        raw = source.get(key)
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    return ""


def _quote_from_history(symbol: str, history: object) -> tuple[float | None, float | None, int | None]:
    """Extract price, daily change %, and volume from a yfinance history frame."""
    if history is None or getattr(history, "empty", True):
        return None, None, None

    closes = history["Close"].dropna()
    volumes = history["Volume"].dropna()
    if closes.empty:
        return None, None, None

    price = _coerce_float(closes.iloc[-1])
    volume = _coerce_int(volumes.iloc[-1]) if not volumes.empty else None
    change_pct: float | None = None
    if len(closes) >= 2:
        previous = _coerce_float(closes.iloc[-2])
        if price is not None and previous not in (None, 0):
            change_pct = ((price - previous) / previous) * 100

    return price, change_pct, volume


def _load_price_history(symbol: str) -> object:
    """Fetch recent daily bars for a ticker using a single yfinance call."""
    with _quiet_yfinance():
        return yf.Ticker(symbol).history(period="5d")


def _load_company_info(symbol: str) -> dict[str, object]:
    """Fetch company metadata only after price data confirms the ticker exists."""
    with _quiet_yfinance():
        stock = yf.Ticker(symbol)
        try:
            raw_info = stock.info
        except Exception as exc:
            logger.debug("yfinance info lookup failed for %s: %s", symbol, exc)
            return {}

    if isinstance(raw_info, dict):
        return raw_info
    return {}


def fetch_quote(ticker: str, fetched_at: datetime | None = None) -> MarketQuote:
    """Fetch a normalized quote for one ticker via yfinance."""
    symbol = ticker.strip().upper()
    if not symbol:
        raise ValueError("Ticker symbol is empty")

    when = fetched_at or datetime.now(tz=UTC)
    history = _load_price_history(symbol)
    price, change_pct, volume = _quote_from_history(symbol, history)

    if price is None:
        raise ValueError(f"Unknown or delisted ticker: {symbol}")

    info = _load_company_info(symbol)

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
        """Use the default MarketDataService unless a test double is injected."""
        self._service = service or MarketDataService()

    def run(self, context: CollectorContext) -> CollectorResult:
        """Fetch quotes for all portfolio tickers and report success/failure counts."""
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
