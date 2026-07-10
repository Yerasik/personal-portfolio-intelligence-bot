"""Portfolio industry inference helpers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

from collectors.market_data import portfolio_tickers
from storage.models import MarketQuote, Portfolio, TickerIndustryMap

if TYPE_CHECKING:
    from analysis.llm import LlmClient
    from storage.repository import DataRepository


def _normalize_industry(label: str) -> str:
    """Return a display-ready industry label, or an empty string if invalid."""
    return " ".join(label.strip().split())


def _normalize_mapping(ticker_to_industry: dict[str, str]) -> dict[str, str]:
    """Normalize mapping keys once so ticker lookups are case-insensitive."""
    normalized: dict[str, str] = {}
    for ticker, industry in ticker_to_industry.items():
        symbol = ticker.strip().upper()
        label = _normalize_industry(industry)
        if symbol and label:
            normalized[symbol] = label
    return normalized


def infer_industries_from_portfolio(
    portfolio: Portfolio,
    ticker_to_industry: dict[str, str],
) -> set[str]:
    """Infer portfolio industries from a static ticker-to-industry mapping."""
    normalized_mapping = _normalize_mapping(ticker_to_industry)
    return {
        industry
        for ticker in portfolio_tickers(portfolio)
        if (industry := normalized_mapping.get(ticker))
    }


def build_news_focus_industries(
    configured_industries: list[str],
    portfolio: Portfolio,
    ticker_to_industry: dict[str, str],
) -> list[str]:
    """Combine configured industries with portfolio-derived industries."""
    seen: set[str] = set()
    combined: list[str] = []

    for industry in configured_industries:
        label = _normalize_industry(industry)
        if label and label.lower() not in seen:
            seen.add(label.lower())
            combined.append(label)

    for industry in sorted(
        infer_industries_from_portfolio(portfolio, ticker_to_industry),
        key=str.lower,
    ):
        if industry.lower() not in seen:
            seen.add(industry.lower())
            combined.append(industry)

    return combined


def build_news_fetch_industries(
    configured_industries: list[str],
    portfolio: Portfolio,
    ticker_to_industry: dict[str, str],
    macro_sector_label: str = "",
) -> list[str]:
    """Industries used for RSS tagging and /news_summary, including macro."""
    focus = build_news_focus_industries(
        configured_industries,
        portfolio,
        ticker_to_industry,
    )
    label = _normalize_industry(macro_sector_label)
    if label and label.lower() not in {industry.lower() for industry in focus}:
        return [label, *focus]
    return focus


def industry_label_from_quote(quote: MarketQuote | None) -> str | None:
    """Pick a display industry label from a yfinance quote (industry preferred over sector)."""
    if quote is None:
        return None
    for raw in (quote.industry, quote.sector):
        label = _normalize_industry(raw)
        if label:
            return label
    return None


def seed_ticker_industry_if_missing(
    repository: DataRepository,
    ticker: str,
    *,
    quote: MarketQuote | None = None,
) -> str | None:
    """Persist yfinance industry/sector for a ticker when not already mapped."""
    symbol = ticker.strip().upper()
    if not symbol:
        return None

    current = repository.load_ticker_industries()
    if _normalize_mapping(current.ticker_to_industry).get(symbol):
        return None

    resolved_quote = quote
    if industry_label_from_quote(resolved_quote) is None:
        state = repository.load_state()
        resolved_quote = state.latest_prices.get(symbol)
    if industry_label_from_quote(resolved_quote) is None:
        from collectors.market_data import ensure_cached_quote

        resolved_quote = ensure_cached_quote(repository, symbol)

    label = industry_label_from_quote(resolved_quote)
    if label is None:
        logger.info("No yfinance industry/sector available to seed for %s", symbol)
        return None

    seeded_label = label

    def _mutate(mapping: TickerIndustryMap) -> TickerIndustryMap:
        updated = dict(mapping.ticker_to_industry)
        if _normalize_mapping(updated).get(symbol):
            return mapping
        updated[symbol] = seeded_label
        return mapping.model_copy(update={"ticker_to_industry": updated})

    repository.mutate_ticker_industries(_mutate)
    logger.info("Seeded ticker_industries.json: %s → %s", symbol, seeded_label)
    return seeded_label


def guess_industry_with_llm(
    llm: LlmClient,
    ticker: str,
    company_name: str = "",
) -> str | None:
    """Best-effort industry guess. Does not persist the result."""
    prompt = (
        "Return one concise stock industry label only.\n"
        f"Ticker: {ticker.strip().upper()}\n"
        f"Company name: {company_name.strip() or 'unknown'}\n"
        "If unsure, return UNKNOWN."
    )
    try:
        response = llm.generate(prompt).strip()
    except Exception as exc:
        logger.warning("Industry guess failed for %s: %s", ticker, exc)
        return None
    if not response or response.upper() == "UNKNOWN":
        return None
    return _normalize_industry(response)
