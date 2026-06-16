#!/usr/bin/env python3
"""Smoke tests for news grouping and LLM summarization helpers."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.news_summarizer import (
    NewsSummary,
    build_sector_summary_prompt,
    build_ticker_summary_prompt,
    news_items_for_sector,
    news_items_for_ticker,
    summarize_daily_news_brief,
    summarize_news,
)
from bot.formatter import format_news_summary, format_news_summary_messages
from bot.i18n import t
from storage.models import AppConfig, NewsCache, NewsItem, Portfolio, Position

NOW = datetime.now(tz=UTC)


class FakeLlm:
    def __init__(self, response: str = "Sector theme bullet.\nTakeaway: mixed.") -> None:
        self.response = response
        self.prompts: list[str] = []

    @property
    def is_configured(self) -> bool:
        return True

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


def _item(
    item_id: str,
    title: str,
    *,
    tickers: list[str] | None = None,
    sectors: list[str] | None = None,
) -> NewsItem:
    return NewsItem(
        id=item_id,
        title=title,
        source="Test",
        url=f"https://example.com/{item_id}",
        published_at=NOW,
        fetched_at=NOW,
        ticker_tags=tickers or [],
        sector_tags=sectors or [],
        summary=title,
    )


def run_test() -> None:
    cache = NewsCache(
        items=[
            _item("s1", "AI chip demand rises", sectors=["AI"]),
            _item("t1", "Apple unveils new iPhone", tickers=["AAPL"], sectors=["Consumer Electronics"]),
            _item("t2", "Apple supply chain update", tickers=["AAPL"]),
            _item("n1", "NVIDIA data center growth", tickers=["NVDA"], sectors=["Semiconductors"]),
        ]
    )
    portfolio = Portfolio(
        positions=[
            Position(ticker="AAPL", shares=10),
            Position(ticker="NVDA", shares=5),
        ]
    )
    config = AppConfig(focus_industries=["AI"])
    mapping = {"AAPL": "Consumer Electronics", "NVDA": "Semiconductors"}

    sector_items = news_items_for_sector(cache, "AI")
    if len(sector_items) != 1 or sector_items[0].id != "s1":
        raise AssertionError(f"unexpected sector items: {sector_items}")

    ticker_items = news_items_for_ticker(cache, "AAPL")
    if len(ticker_items) != 2:
        raise AssertionError(f"expected 2 AAPL items, got {len(ticker_items)}")

    sector_prompt = build_sector_summary_prompt("AI", sector_items)
    if (
        "Sector: AI" not in sector_prompt
        or "Developments:" not in sector_prompt
        or "1. AI chip demand rises" not in sector_prompt
        or "Do not merge" not in sector_prompt
    ):
        raise AssertionError("sector prompt missing expected structured instructions")

    ticker_prompt = build_ticker_summary_prompt(
        "NVDA",
        "NVIDIA Corporation",
        news_items_for_ticker(cache, "NVDA"),
    )
    if (
        "Ticker: NVDA" not in ticker_prompt
        or "Developments:" not in ticker_prompt
        or "shareholder" not in ticker_prompt.lower()
    ):
        raise AssertionError("ticker prompt missing expected structured instructions")

    llm = FakeLlm("- Theme one\n- Theme two\nTakeaway: constructive.")
    summary = summarize_news(
        llm,
        portfolio,
        config,
        cache,
        mapping,
        company_names={"NVDA": "NVIDIA Corporation"},
    )
    if "Consumer Electronics" not in summary.sector_summaries:
        raise AssertionError("portfolio-derived sector missing from summaries")
    if summary.ticker_summaries.get("AAPL") == "No recent news items for this ticker in the cache.":
        raise AssertionError("AAPL should have news")
    if not llm.prompts:
        raise AssertionError("LLM should be called for groups with news")

    empty = summarize_news(
        FakeLlm(),
        Portfolio(positions=[Position(ticker="ZZZZ", shares=1)]),
        config,
        NewsCache(),
        mapping,
    )
    if empty.ticker_summaries["ZZZZ"] != t("news_no_ticker_cache", "en"):
        raise AssertionError(f"unexpected empty ticker message: {empty.ticker_summaries}")

    rendered_ru = format_news_summary(
        NewsSummary(
            sector_summaries={"AI": "Сводка по ИИ."},
            ticker_summaries={"AAPL": t("news_no_ticker_cache", "ru")},
        ),
        lang="ru",
    )
    if t("news_no_ticker_cache", "ru") not in rendered_ru:
        raise AssertionError("Russian news summary should keep localized empty ticker text")

    rendered = format_news_summary(
        NewsSummary(
            sector_summaries={"AI": "AI theme summary."},
            ticker_summaries={"AAPL": "Apple product news."},
        )
    )
    if "News by sector" not in rendered or "News by ticker" not in rendered:
        raise AssertionError(f"formatter missing sections: {rendered}")

    chunks = format_news_summary_messages(
        NewsSummary(
            sector_summaries={"AI": "AI theme summary."},
            ticker_summaries={"AAPL": "Apple product news."},
        )
    )
    if len(chunks) < 4:
        raise AssertionError(f"expected multiple messages, got {len(chunks)}")
    if any(len(chunk) > 4096 for chunk in chunks):
        raise AssertionError("a split message exceeds Telegram limit")

    daily_brief = summarize_daily_news_brief(
        llm,
        portfolio,
        config,
        cache,
        mapping,
        company_names={"NVDA": "NVIDIA Corporation"},
    )
    if daily_brief.sector_summaries:
        raise AssertionError("daily brief should not include sectors")
    if "AAPL" not in daily_brief.ticker_summaries:
        raise AssertionError("daily brief should include AAPL ticker news")

    print("News summarizer checks passed.")


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
