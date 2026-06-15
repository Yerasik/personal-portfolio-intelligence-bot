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
    "You are a cautious financial news analyst. Your job is to restate each "
    "provided headline in clear, separate bullet points — not to write a "
    "blended narrative. This is not investment advice."
)

_TICKER_ROLE = (
    "You are a cautious equity research assistant. Your job is to restate each "
    "provided headline about one company in clear, separate bullet points — "
    "not to write a blended narrative. This is not investment advice."
)

_OUTPUT_RULES = (
    "Rules:\n"
    "- Write exactly one numbered line under Developments for each input item.\n"
    "- Each line must cover ONLY that item. Do not merge, combine, or link "
    "separate stories with words like while, also, as well, meanwhile, or "
    "in addition.\n"
    "- Do not invent facts, figures, dates, or causes not stated in that item.\n"
    "- If an item is vague, say so on that line only.\n"
    "- Keep each development line under 25 words.\n"
    "- Use only the items above."
)


def _numbered_news_block(items: list[NewsItem]) -> str:
    """Format news as a numbered list the model must mirror one-to-one."""
    lines = [
        f"{index}. {_format_item_line(item)}"
        for index, item in enumerate(items, start=1)
    ]
    return "\n".join(lines)


def _summary_output_template(*, language: str) -> str:
    """Shared output skeleton for sector and ticker summaries."""
    from bot.i18n import llm_language_clause

    return (
        "Output format (follow exactly):\n"
        "Developments:\n"
        "1. <one sentence for news item 1 only>\n"
        "2. <one sentence for news item 2 only>\n"
        "(continue numbering until every input item has a matching line)\n"
        "Overall: <one sentence on sentiment or key risk; if items are unrelated, "
        'say "mixed or unrelated coverage">'
        f"\n\n{_OUTPUT_RULES}\n"
        f"{llm_language_clause(language)}"
    )

_NO_SECTOR_NEWS_KEY = "news_no_sector_cache"
_NO_TICKER_NEWS_KEY = "news_no_ticker_cache"
_LLM_DISABLED_KEY = "news_llm_disabled"


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
    items: list[NewsItem],
    *,
    language: str = "en",
) -> str:
    """Build a grounded prompt for sector-level news summarization."""
    news_block = _numbered_news_block(items)
    item_count = len(items)
    return (
        f"{_SECTOR_ROLE}\n\n"
        f"Sector: {sector.strip()}\n"
        f"News items ({item_count}):\n{news_block}\n\n"
        f"{_summary_output_template(language=language)}"
    )


def build_ticker_summary_prompt(
    ticker: str,
    company_name: str,
    items: list[NewsItem],
    *,
    language: str = "en",
) -> str:
    """Build a grounded prompt for per-ticker news summarization."""
    news_block = _numbered_news_block(items)
    name = company_name.strip() or "unknown"
    item_count = len(items)
    return (
        f"{_TICKER_ROLE}\n\n"
        f"Ticker: {ticker.strip().upper()}\n"
        f"Company: {name}\n"
        f"News items ({item_count}):\n{news_block}\n\n"
        "Focus each development line on shareholder-relevant facts from that "
        "headline only (earnings, guidance, regulation, products, competition).\n\n"
        f"{_summary_output_template(language=language)}"
    )


def _clip_summary(text: str) -> str:
    cleaned = text.strip()
    if len(cleaned) <= MAX_SUMMARY_CHARS:
        return cleaned
    return cleaned[: MAX_SUMMARY_CHARS - 20].rstrip() + "\n…(truncated)"


def _deterministic_fallback(
    label: str,
    items: list[NewsItem],
    *,
    language: str = "en",
) -> str:
    """Headline-only fallback when the LLM is unavailable."""
    from bot.i18n import t

    if not items:
        return t("news_no_items_cache", language, label=label)
    lines = [t("news_fallback_headlines", language, label=label)]
    lines.extend(f"- {item.title}" for item in items[:5])
    if len(items) > 5:
        lines.append(t("news_fallback_plus_more", language, count=len(items) - 5))
    return _clip_summary("\n".join(lines))


def _summarize_group(
    llm: LlmClient,
    prompt: str,
    *,
    label: str,
    items: list[NewsItem],
    language: str = "en",
) -> str:
    """Call the LLM for one group; fall back to headlines on failure."""
    if not getattr(llm, "is_configured", False):
        return _deterministic_fallback(label, items, language=language)

    try:
        response = llm.generate(prompt)
        if not response.strip():
            return _deterministic_fallback(label, items, language=language)
        return _clip_summary(response)
    except Exception as exc:
        logger.warning("News summary failed for %s: %s", label, exc)
        return _deterministic_fallback(label, items, language=language)


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
    from bot.i18n import t

    names = company_names or {}
    focus_industries = build_news_focus_industries(
        app_config.focus_industries,
        portfolio,
        ticker_to_industry,
    )
    tickers = portfolio_tickers(portfolio)

    if not enabled:
        disabled_message = t(_LLM_DISABLED_KEY, language)
        return NewsSummary(
            sector_summaries={s: disabled_message for s in focus_industries},
            ticker_summaries={ticker: disabled_message for ticker in tickers},
            source="disabled",
        )

    sector_summaries: dict[str, str] = {}
    for sector in focus_industries:
        items = news_items_for_sector(news_cache, sector)
        if not items:
            sector_summaries[sector] = t(_NO_SECTOR_NEWS_KEY, language)
            continue
        prompt = build_sector_summary_prompt(sector, items, language=language)
        sector_summaries[sector] = _summarize_group(
            llm,
            prompt,
            label=sector,
            items=items,
            language=language,
        )

    ticker_summaries: dict[str, str] = {}
    for symbol in tickers:
        items = news_items_for_ticker(news_cache, symbol)
        if not items:
            ticker_summaries[symbol] = t(_NO_TICKER_NEWS_KEY, language)
            continue
        prompt = build_ticker_summary_prompt(
            symbol,
            names.get(symbol, ""),
            items,
            language=language,
        )
        ticker_summaries[symbol] = _summarize_group(
            llm,
            prompt,
            label=symbol,
            items=items,
            language=language,
        )

    return NewsSummary(
        sector_summaries=sector_summaries,
        ticker_summaries=ticker_summaries,
        source="llm",
    )
