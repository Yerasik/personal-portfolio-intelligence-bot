#!/usr/bin/env python3
"""Smoke test for the news data collector."""

from __future__ import annotations

import json
import logging
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collectors import news_data as news_data_module
from collectors.news_data import NewsDataService, make_article_id, tag_sectors
from storage.models import AppConfig, MarketQuote, Portfolio, Position
from storage.paths import resolve_data_paths
from storage.repository import DataRepository

from email.utils import format_datetime

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")

PUB_DATE = format_datetime(datetime.now(tz=UTC))

SAMPLE_RSS = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Finance Feed</title>
    <item>
      <title>Apple Inc. announces new product line</title>
      <link>https://news.example.com/apple-product</link>
      <guid>https://news.example.com/apple-product</guid>
      <pubDate>{PUB_DATE}</pubDate>
      <description>Apple Inc. unveiled updates across its consumer electronics lineup.</description>
    </item>
    <item>
      <title>Generic market wrap with no tracked keywords</title>
      <link>https://news.example.com/generic-wrap</link>
      <guid>https://news.example.com/generic-wrap</guid>
      <pubDate>{PUB_DATE}</pubDate>
      <description>Broad market commentary without portfolio keywords.</description>
    </item>
  </channel>
</rss>
"""


def _mock_fetch_feed(url: str, timeout: float = 30.0):
    import feedparser

    _ = url, timeout
    return feedparser.parse(SAMPLE_RSS)


def run_test() -> None:
    if tag_sectors("Analysts said earnings would improve", ["AI"]):
        raise AssertionError("AI should not match inside unrelated words like 'said'")
    if "AI" not in tag_sectors("New AI chip demand lifts sector", ["AI"]):
        raise AssertionError("AI should match as a standalone industry keyword")
    if "China-US Relations" not in tag_sectors(
        "US-China tariffs escalate amid trade talks",
        ["China-US Relations"],
        {"China-US Relations": ["US-China", "tariffs"]},
    ):
        raise AssertionError("sector_keywords should tag articles via aliases")

    temp_dir = Path(tempfile.mkdtemp(prefix="news-data-test-"))
    print(f"Using temp data dir: {temp_dir}")

    try:
        paths = resolve_data_paths(temp_dir)
        repository = DataRepository(paths)

        repository.save_config(
            AppConfig(
                rss_feed_urls=["https://feeds.example.com/finance.xml"],
                focus_industries=["Consumer Electronics"],
            )
        )
        repository.save_portfolio(
            Portfolio(positions=[Position(ticker="AAPL", shares=1)])
        )

        state = repository.load_state()
        state.latest_prices["AAPL"] = MarketQuote(
            ticker="AAPL",
            price=190.0,
            change_pct=1.2,
            volume=1000,
            company_name="Apple Inc.",
            sector="Technology",
            industry="Consumer Electronics",
            currency="USD",
            fetched_at=datetime.now(tz=UTC),
        )
        repository.save_state(state)

        service = NewsDataService()
        with patch.object(news_data_module, "fetch_feed", side_effect=_mock_fetch_feed):
            batch = service.run(repository, repository.load_config())

        print(f"New articles: {batch.new_count}")
        print(f"Untagged skipped: {batch.entries_skipped_untagged}")

        cache = repository.load_news_cache()
        if batch.new_count != 1:
            raise AssertionError(f"expected 1 new article, got {batch.new_count}")
        if batch.entries_skipped_untagged != 1:
            raise AssertionError("expected 1 untagged article to be skipped")

        article = cache.items[0]
        print(f"Article id={article.id} tickers={article.ticker_tags}")
        if article.ticker_tags != ["AAPL"]:
            raise AssertionError(f"unexpected ticker tags: {article.ticker_tags}")
        if "Consumer Electronics" not in article.sector_tags:
            raise AssertionError(f"expected sector tag, got {article.sector_tags}")
        if article.processed or article.alert_sent:
            raise AssertionError("new articles should start unprocessed")

        expected_id = make_article_id("https://news.example.com/apple-product")
        if article.id != expected_id:
            raise AssertionError(f"unexpected article id: {article.id}")

        # Second run should dedupe the same article.
        with patch.object(news_data_module, "fetch_feed", side_effect=_mock_fetch_feed):
            second_batch = service.run(repository, repository.load_config())
        if second_batch.new_count != 0:
            raise AssertionError("duplicate article should not be added twice")
        if second_batch.entries_skipped_duplicate != 1:
            raise AssertionError("duplicate article should be counted")

        updated_state = repository.load_state()
        if updated_state.last_news_fetch_at is None:
            raise AssertionError("last_news_fetch_at was not updated")

        print("news_cache.json snapshot:")
        print(json.dumps(cache.model_dump(mode="json"), indent=2))
        print("News data collector checks passed.")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
