#!/usr/bin/env python3
"""Smoke tests for deterministic news sentiment scoring."""

from __future__ import annotations

import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.sentiment_analyzer import SentimentAnalyzer, run_sentiment_analysis
from storage.models import NewsCache, NewsItem
from storage.paths import resolve_data_paths
from storage.repository import DataRepository

NOW = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)


def run_test() -> None:
    analyzer = SentimentAnalyzer()

    bullish = analyzer.score(
        "Company beat estimates with record profit, strong demand, and an upgrade."
    )
    if bullish <= 0:
        raise AssertionError(f"expected bullish score > 0, got {bullish}")

    bearish = analyzer.score(
        "Company miss expectations after layoffs, cut guidance, and weak demand."
    )
    if bearish >= 0:
        raise AssertionError(f"expected bearish score < 0, got {bearish}")

    neutral = analyzer.score("Company reports quarterly results for shareholders.")
    if abs(neutral) >= 0.3:
        raise AssertionError(f"expected neutral score near 0, got {neutral}")

    grouped = analyzer.score_articles(
        [
            {
                "title": "NVDA beat profit estimates",
                "summary": "",
                "ticker_tags": ["NVDA"],
            },
            {
                "title": "NVDA faces weak demand concerns",
                "summary": "",
                "ticker_tags": ["NVDA"],
            },
            {
                "title": "Unrelated market wrap",
                "summary": "",
                "ticker_tags": ["AAPL"],
            },
        ]
    )
    if "NVDA" not in grouped or "AAPL" not in grouped:
        raise AssertionError(f"expected grouped tickers, got {grouped}")

    temp_dir = Path(tempfile.mkdtemp(prefix="sentiment-test-"))
    try:
        repository = DataRepository(resolve_data_paths(temp_dir))
        repository.save_news_cache(
            NewsCache(
                items=[
                    NewsItem(
                        id="n1",
                        title="Alibaba beat estimates with record profit",
                        source="Test",
                        url="https://example.com/n1",
                        fetched_at=NOW,
                        ticker_tags=["9988.HK"],
                    ),
                    NewsItem(
                        id="n2",
                        title="Alibaba faces downgrade after weak demand",
                        source="Test",
                        url="https://example.com/n2",
                        fetched_at=NOW,
                        ticker_tags=["9988.HK"],
                    ),
                ],
                updated_at=NOW,
            )
        )

        scores = run_sentiment_analysis(repository)
        if "9988.HK" not in scores:
            raise AssertionError("sentiment job should score tagged ticker")

        signals = repository.load_signals()
        record = signals.sentiment.get("9988.HK")
        if record is None or record.article_count != 2:
            raise AssertionError("signals.json sentiment record missing or wrong count")
        if record.updated_at is None:
            raise AssertionError("signals.json should include updated_at")

        print("Sentiment analyzer checks passed.")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
