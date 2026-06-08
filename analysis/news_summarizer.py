"""LLM-powered summaries of cached news by sector and portfolio ticker."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from analysis.industries import build_news_focus_industries
from collectors.market_data import portfolio_tickers
from storage.models import AppConfig, NewsCache, NewsItem, Portfolio

if TYPE_CHECKING:
    from analysis.llm import LlmClient

logger = logging.getLogger(__name__)

MAX_ITEMS_PER_GROUP = 8
_SUMMARY_CLIP = 200
MAX_SUMMARY_CHARS = 1200

SummarySource = Literal["llm", "fallback", "disabled"]

_SECTOR_ROLE = (
    "You are a cautious financial news analyst. Summarize ONLY the provided "
    "headlines for a sector/industry. Do not invent facts, figures, or events. "
    "If the list is short, say so. This is not investment advice."
)

_TICKER_ROLE = (
    "You are a cautious equity research assistant. Summarize ONLY the provided "
    "headlines for one company. Focus on what matters to a shareholder "
    "(earnings, guidance, regulation, products, competition). Do not invent "
    "facts. This is not investment advice."
)

_NO_SECTOR_NEWS = "No recent news items for this sector in the cache."
_NO_TICKER_NEWS = "No recent news items for this ticker in the cache."
_LLM_DISABLED = "LLM summaries disabled (set enable_llm_summaries in config.json)."


@dataclass(frozen=True)
class NewsSummary:
    """Sector- and ticker-level news summaries."""

    sector_summaries: dict[str, str]
    ticker_summaries: dict[str, str]
    source: SummarySource = "llm"


def _item_timestamp(item: NewsItem) -> Any:
    return item.published_at or item.fetched_at


def _format_item_line(item: NewsItem) -> str:
    summary = item.summary.strip()
    if summary:
        clipped = summary[:_SUMMARY_CLIP].rstrip()
        return f"{item.title} — {clipped}"
    return item.title


def news_items_for_sector(news_cache: NewsCache, sector: str) -> list[NewsItem]:
    """Return recent news tagged with the given sector label."""
    label = sector.strip()
    if not label:
        return []
    matched = [item for item in news_cache.items if label in item.sector_tags]
    matched.sort(key=_item_timestamp, reverse=True)
    return matched[:MAX_ITEMS_PER_GROUP]


def news_items_for_ticker(news_cache: NewsCache, ticker: str) -> list[NewsItem]:
    """Return recent news tagged with the given ticker symbol."""
    symbol = ticker.strip().upper()
    if not symbol:
        return []
    matched = [item for item in news_cache.items if symbol in item.ticker_tags]
    matched.sort(key=_item_timestamp, reverse=True)
    return matched[:MAX_ITEMS_PER_GROUP]


def build_sector_summary_prompt(
    sector: str,
    item_lines: list[str],
    *,
    language: str = "en",
) -> str:
    """Build a grounded prompt for sector-level news summarization."""
    from bot.i18n import llm_language_clause

    news_block = "\n".join(f"- {line}" for line in item_lines)
    return (
        f"{_SECTOR_ROLE}\n\n"
        f"Sector: {sector.strip()}\n"
        f"News items:\n{news_block}\n\n"
        "Write a concise summary with:\n"
        "- 2–4 bullet points on the main themes\n"
        "- One short sentence on overall sentiment or key risks\n"
        f"{llm_language_clause(language)}\n"
        "Use only the items above. If coverage is thin, say so explicitly."
    )


def build_ticker_summary_prompt(
    ticker: str,
    company_name: str,
    item_lines: list[str],
    *,
    language: str = "en",
) -> str:
    """Build a grounded prompt for per-ticker news summarization."""
    from bot.i18n import llm_language_clause

    news_block = "\n".join(f"- {line}" for line in item_lines)
    name = company_name.strip() or "unknown"
    return (
        f"{_TICKER_ROLE}\n\n"
        f"Ticker: {ticker.strip().upper()}\n"
        f"Company: {name}\n"
        f"News items:\n{news_block}\n\n"
        "Write a concise shareholder-focused summary with:\n"
        "- 2–4 bullet points on the most relevant developments\n"
        "- One short takeaway sentence\n"
        f"{llm_language_clause(language)}\n"
        "Use only the items above. If coverage is thin, say so explicitly."
    )


def _clip_summary(text: str) -> str:
    cleaned = text.strip()
    if len(cleaned) <= MAX_SUMMARY_CHARS:
        return cleaned
    return cleaned[: MAX_SUMMARY_CHARS - 20].rstrip() + "\n…(truncated)"


def _deterministic_fallback(label: str, items: list[NewsItem]) -> str:
    """Headline-only fallback when the LLM is unavailable."""
    if not items:
        return f"No recent news items for {label} in the cache."
    lines = [f"Recent headlines for {label} (LLM unavailable):"]
    lines.extend(f"- {item.title}" for item in items[:5])
    if len(items) > 5:
        lines.append(f"- plus {len(items) - 5} more")
    return _clip_summary("\n".join(lines))


def _summarize_group(
    llm: LlmClient,
    prompt: str,
    *,
    label: str,
    items: list[NewsItem],
) -> str:
    """Call the LLM for one group; fall back to headlines on failure."""
    if not getattr(llm, "is_configured", False):
        return _deterministic_fallback(label, items)

    try:
        response = llm.generate(prompt)
        if not response.strip():
            return _deterministic_fallback(label, items)
        return _clip_summary(response)
    except Exception as exc:
        logger.warning("News summary failed for %s: %s", label, exc)
        return _deterministic_fallback(label, items)


def summarize_news(
    llm: LlmClient,
    portfolio: Portfolio,
    app_config: AppConfig,
    news_cache: NewsCache,
    ticker_to_industry: dict[str, str],
    *,
    company_names: dict[str, str] | None = None,
    enabled: bool = True,
    language: str = "en",
) -> NewsSummary:
    """Produce sector- and ticker-level summaries from the news cache."""
    names = company_names or {}
    focus_industries = build_news_focus_industries(
        app_config.focus_industries,
        portfolio,
        ticker_to_industry,
    )
    tickers = portfolio_tickers(portfolio)

    if not enabled:
        return NewsSummary(
            sector_summaries={s: _LLM_DISABLED for s in focus_industries},
            ticker_summaries={t: _LLM_DISABLED for t in tickers},
            source="disabled",
        )

    sector_summaries: dict[str, str] = {}
    for sector in focus_industries:
        items = news_items_for_sector(news_cache, sector)
        if not items:
            sector_summaries[sector] = _NO_SECTOR_NEWS
            continue
        lines = [_format_item_line(item) for item in items]
        prompt = build_sector_summary_prompt(sector, lines, language=language)
        sector_summaries[sector] = _summarize_group(
            llm, prompt, label=sector, items=items
        )

    ticker_summaries: dict[str, str] = {}
    for symbol in tickers:
        items = news_items_for_ticker(news_cache, symbol)
        if not items:
            ticker_summaries[symbol] = _NO_TICKER_NEWS
            continue
        lines = [_format_item_line(item) for item in items]
        prompt = build_ticker_summary_prompt(
            symbol,
            names.get(symbol, ""),
            lines,
            language=language,
        )
        ticker_summaries[symbol] = _summarize_group(
            llm, prompt, label=symbol, items=items
        )

    return NewsSummary(
        sector_summaries=sector_summaries,
        ticker_summaries=ticker_summaries,
        source="llm",
    )
