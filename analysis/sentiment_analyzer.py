"""Deterministic news sentiment scoring (no LLM)."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime

from storage.models import SignalsFile, TickerSentimentSignal
from storage.portfolio_ops import normalize_ticker
from storage.repository import DataRepository

logger = logging.getLogger(__name__)


class SentimentAnalyzer:
    """Score cached news text for portfolio tickers."""

    BULLISH_TERMS: tuple[str, ...] = (
        "beat",
        "upgrade",
        "partnership",
        "record",
        "expansion",
        "buyback",
        "profit",
        "raised guidance",
        "strong demand",
        "outperform",
    )
    BEARISH_TERMS: tuple[str, ...] = (
        "miss",
        "downgrade",
        "recall",
        "investigation",
        "layoff",
        "decline",
        "loss",
        "cut guidance",
        "weak demand",
        "underperform",
    )

    def score(self, text: str) -> float:
        """Return a sentiment score from -1.0 (bearish) to +1.0 (bullish)."""
        normalized = text.lower()
        bull = sum(1 for term in self.BULLISH_TERMS if term in normalized)
        bear = sum(1 for term in self.BEARISH_TERMS if term in normalized)
        return (bull - bear) / (bull + bear + 1)

    def score_articles(self, articles: list[dict]) -> dict[str, float]:
        """Group articles by ticker tag and return average sentiment per ticker."""
        scores_by_ticker: dict[str, list[float]] = defaultdict(list)
        for article in articles:
            text = _article_text(article)
            article_score = self.score(text)
            for ticker in _article_tickers(article):
                scores_by_ticker[ticker].append(article_score)

        return {
            ticker: sum(values) / len(values)
            for ticker, values in scores_by_ticker.items()
            if values
        }

    def persist_scores(
        self,
        repository: DataRepository,
        articles: list[dict],
        *,
        updated_at: datetime | None = None,
    ) -> dict[str, float]:
        """Score articles, persist under signals.json → sentiment, and return averages."""
        scores = self.score_articles(articles)
        now = updated_at or datetime.now(tz=UTC)
        counts = _article_counts_by_ticker(articles)

        signals = repository.load_signals()
        signals.sentiment = {
            ticker: TickerSentimentSignal(
                score=score,
                updated_at=now,
                article_count=counts.get(ticker, 0),
            )
            for ticker, score in scores.items()
        }
        repository.save_signals(signals)
        logger.info(
            "Persisted sentiment for %d ticker(s) to signals.json",
            len(signals.sentiment),
        )
        return scores


def news_cache_to_article_dicts(news_cache) -> list[dict]:
    """Convert cached NewsItem rows to plain dicts for scoring."""
    return [item.model_dump(mode="json") for item in news_cache.items]


def run_sentiment_analysis(repository: DataRepository) -> dict[str, float]:
    """Read news_cache.json, score per ticker, and write signals.json."""
    news_cache = repository.load_news_cache()
    articles = news_cache_to_article_dicts(news_cache)
    return SentimentAnalyzer().persist_scores(repository, articles)


def _article_text(article: dict) -> str:
    title = str(article.get("title", "")).strip()
    summary = str(article.get("summary", "")).strip()
    if title and summary:
        return f"{title} {summary}"
    return title or summary


def _article_tickers(article: dict) -> list[str]:
    raw_tags = article.get("ticker_tags") or []
    tickers: list[str] = []
    seen: set[str] = set()
    for tag in raw_tags:
        symbol = normalize_ticker(str(tag))
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        tickers.append(symbol)
    return tickers


def _article_counts_by_ticker(articles: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for article in articles:
        for ticker in _article_tickers(article):
            counts[ticker] += 1
    return dict(counts)
