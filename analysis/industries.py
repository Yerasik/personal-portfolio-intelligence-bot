"""Portfolio industry inference helpers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

from collectors.market_data import portfolio_tickers
from storage.models import Portfolio

if TYPE_CHECKING:
    from analysis.llm import LlmClient


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
