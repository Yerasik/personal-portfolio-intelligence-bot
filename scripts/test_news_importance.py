#!/usr/bin/env python3
"""Smoke tests for top headline selection."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.news_selection import select_top_global_articles
from storage.models import NewsItem

NOW = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)


def _item(
    item_id: str,
    title: str,
    *,
    tickers: list[str] | None = None,
    sectors: list[str] | None = None,
    hours_ago: int = 1,
) -> NewsItem:
    ts = NOW - timedelta(hours=hours_ago)
    return NewsItem(
        id=item_id,
        title=title,
        source="Test",
        url=f"https://example.com/{item_id}",
        published_at=ts,
        fetched_at=ts,
        ticker_tags=tickers or [],
        sector_tags=sectors or [],
    )


def run_test() -> None:
    items = [
        _item("t1", "Alibaba shares fall after downgrade", tickers=["9988.HK"], sectors=["Hong Kong"]),
        _item("t2", "Federal Reserve holds rates steady", sectors=["Macro & Central Banks"]),
        _item("t3", "Random sports headline about cricket", sectors=["Sports"]),
        _item("t4", "Fed signals patience on inflation", sectors=["Macro & Central Banks"], hours_ago=2),
        _item("t5", "Vertiv wins data center contract", tickers=["VRT"], sectors=["Data Center Infrastructure"]),
        _item("t6", "Alibaba shares fall after downgrade - Reuters", tickers=["9988.HK"], hours_ago=2),
        _item("t7", "Semiconductor demand outlook improves", sectors=["Semiconductors"]),
    ]

    ranked = select_top_global_articles(
        items,
        portfolio_symbols={"9988.HK", "VRT"},
        macro_label="Macro & Central Banks",
        macro_keywords=["federal reserve", "fed", "inflation"],
        max_items=5,
        window_hours=24,
        now=NOW,
    )

    if len(ranked) < 3:
        raise AssertionError(f"expected at least 3 ranked items, got {len(ranked)}")

    labels = {row.label for row in ranked}
    if "Macro & Central Banks" in labels:
        raise AssertionError("macro headlines should be excluded from daily top selection")

    titles = [row.item.title for row in ranked]
    if any("Federal Reserve" in title or "Fed signals" in title for title in titles):
        raise AssertionError("macro articles should be excluded from daily top selection")

    if sum("Alibaba shares fall" in title for title in titles) > 1:
        raise AssertionError("duplicate Alibaba headline should be deduped")

    if not any("Vertiv" in title for title in titles):
        raise AssertionError("portfolio-related article should rank in top selection")

    print("Top headline selection checks passed.")


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
