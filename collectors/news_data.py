"""News feed collection and cache updates."""

from __future__ import annotations

import hashlib
import logging
import re
from calendar import timegm
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from html import unescape
from typing import Any
from urllib.parse import urlparse

import feedparser
import httpx

from collectors.base import BaseCollector, CollectorContext, CollectorResult
from collectors.market_data import portfolio_tickers
from storage.models import AppConfig, BotState, MarketQuote, NewsCache, NewsItem, Portfolio
from storage.repository import DataRepository

logger = logging.getLogger(__name__)

DEFAULT_FETCH_TIMEOUT_SECONDS = 30.0
_HTML_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class NewsFetchBatchResult:
    """Outcome of a news collection run."""

    new_items: list[NewsItem] = field(default_factory=list)
    feeds_fetched: int = 0
    feeds_failed: int = 0
    entries_seen: int = 0
    entries_skipped_duplicate: int = 0
    entries_skipped_untagged: int = 0
    fetched_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))

    @property
    def new_count(self) -> int:
        return len(self.new_items)


def make_article_id(url: str, entry_id: str | None = None) -> str:
    """Build a stable article id from the feed entry id or canonical URL."""
    stable = (entry_id or url).strip()
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]


def _strip_html(text: str) -> str:
    cleaned = _HTML_TAG_RE.sub(" ", text)
    return unescape(re.sub(r"\s+", " ", cleaned)).strip()


def _parse_feed_datetime(parsed: Any) -> datetime | None:
    if not parsed:
        return None
    try:
        return datetime.fromtimestamp(timegm(parsed), tz=UTC)
    except (OverflowError, OSError, TypeError, ValueError):
        return None


def _feed_source_name(feed: feedparser.FeedParserDict, feed_url: str) -> str:
    feed_title = getattr(feed.feed, "title", "") if hasattr(feed, "feed") else ""
    if feed_title:
        return str(feed_title).strip()
    return urlparse(feed_url).netloc or feed_url


def _contains_ticker_keyword(text: str, keyword: str) -> bool:
    symbol = keyword.strip()
    if not symbol:
        return False
    if " " in symbol:
        return symbol.lower() in text.lower()
    pattern = rf"\b{re.escape(symbol)}\b"
    return bool(re.search(pattern, text, flags=re.IGNORECASE))


def build_ticker_keywords(
    portfolio: Portfolio,
    watchlist: list[str],
    latest_prices: dict[str, MarketQuote],
) -> dict[str, list[str]]:
    """Map tickers to keyword lists used for simple article tagging."""
    keywords: dict[str, list[str]] = {}
    symbols = portfolio_tickers(portfolio)
    for symbol in watchlist:
        normalized = symbol.strip().upper()
        if normalized and normalized not in symbols:
            symbols.append(normalized)

    for symbol in symbols:
        terms = [symbol]
        quote = latest_prices.get(symbol)
        if quote and quote.company_name:
            terms.append(quote.company_name)
        keywords[symbol] = terms
    return keywords


def tag_tickers(text: str, ticker_keywords: dict[str, list[str]]) -> list[str]:
    """Return tickers whose keywords appear in the article text."""
    matched: list[str] = []
    for symbol, keywords in ticker_keywords.items():
        if any(_contains_ticker_keyword(text, keyword) for keyword in keywords):
            matched.append(symbol)
    return sorted(set(matched))


def tag_sectors(text: str, focus_industries: list[str]) -> list[str]:
    """Return focus industries mentioned in the article text."""
    matched: list[str] = []
    for industry in focus_industries:
        label = industry.strip()
        if label and _contains_ticker_keyword(text, label):
            matched.append(label)
    return sorted(set(matched))


def normalize_entry(
    entry: Any,
    *,
    feed_url: str,
    feed_source: str,
    fetched_at: datetime,
    ticker_keywords: dict[str, list[str]],
    focus_industries: list[str],
) -> NewsItem | None:
    """Convert one RSS entry into a normalized NewsItem when it matches tags."""
    url = str(getattr(entry, "link", "") or getattr(entry, "id", "")).strip()
    title = _strip_html(str(getattr(entry, "title", "") or "")).strip()
    if not url or not title:
        return None

    summary = _strip_html(
        str(
            getattr(entry, "summary", "")
            or getattr(entry, "description", "")
            or ""
        )
    )
    tag_text = " ".join(part for part in (title, summary) if part)
    ticker_tags = tag_tickers(tag_text, ticker_keywords)
    sector_tags = tag_sectors(tag_text, focus_industries)
    if not ticker_tags and not sector_tags:
        return None

    published_at = _parse_feed_datetime(
        getattr(entry, "published_parsed", None)
        or getattr(entry, "updated_parsed", None)
    )
    entry_id = str(getattr(entry, "id", "") or "").strip() or None

    return NewsItem(
        id=make_article_id(url, entry_id),
        title=title,
        source=feed_source,
        url=url,
        published_at=published_at,
        fetched_at=fetched_at,
        ticker_tags=ticker_tags,
        sector_tags=sector_tags,
        summary=summary[:500],
    )


def fetch_feed(url: str, timeout: float = DEFAULT_FETCH_TIMEOUT_SECONDS) -> feedparser.FeedParserDict:
    """Download and parse one RSS/Atom feed."""
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
    return feedparser.parse(response.text)


def apply_retention(
    items: list[NewsItem],
    *,
    max_items: int,
    retention_days: int,
    now: datetime,
) -> list[NewsItem]:
    """Drop stale articles and cap total cache size."""
    cutoff = now - timedelta(days=retention_days)

    def item_timestamp(item: NewsItem) -> datetime:
        return item.published_at or item.fetched_at

    kept = [item for item in items if item_timestamp(item) >= cutoff]
    kept.sort(key=item_timestamp, reverse=True)
    return kept[:max_items]


def merge_news_cache(
    existing: NewsCache,
    new_items: list[NewsItem],
    *,
    max_items: int,
    retention_days: int,
    now: datetime,
) -> tuple[NewsCache, int, int]:
    """Merge new articles into the cache, skipping duplicates."""
    by_id = {item.id: item for item in existing.items}
    duplicates = 0

    for item in new_items:
        if item.id in by_id:
            duplicates += 1
            continue
        by_id[item.id] = item

    merged_items = apply_retention(
        list(by_id.values()),
        max_items=max_items,
        retention_days=retention_days,
        now=now,
    )
    return NewsCache(items=merged_items, updated_at=now), duplicates, len(merged_items)


class NewsDataService:
    """Fetch RSS feeds, tag articles, and persist news_cache.json."""

    def fetch_batch(
        self,
        app_config: AppConfig,
        portfolio: Portfolio,
        latest_prices: dict[str, MarketQuote],
        existing_cache: NewsCache,
        focus_industries: list[str] | None = None,
    ) -> NewsFetchBatchResult:
        """Fetch configured feeds and return newly tagged articles."""
        fetched_at = datetime.now(tz=UTC)
        result = NewsFetchBatchResult(fetched_at=fetched_at)
        feed_urls = [url.strip() for url in app_config.rss_feed_urls if url.strip()]
        industry_keywords = focus_industries or app_config.focus_industries

        if not feed_urls:
            logger.info("No RSS feed URLs configured")
            return result

        ticker_keywords = build_ticker_keywords(
            portfolio,
            app_config.extra_watchlist,
            latest_prices,
        )
        existing_ids = {item.id for item in existing_cache.items}
        collected: list[NewsItem] = []

        logger.info("Fetching news from %d RSS feed(s)", len(feed_urls))

        for feed_url in feed_urls:
            try:
                feed = fetch_feed(feed_url)
            except Exception as exc:
                result.feeds_failed += 1
                logger.warning("RSS fetch failed for %s: %s", feed_url, exc)
                continue

            result.feeds_fetched += 1
            feed_source = _feed_source_name(feed, feed_url)
            entries = getattr(feed, "entries", []) or []
            logger.info("Parsed %d entries from %s", len(entries), feed_source)

            for entry in entries:
                result.entries_seen += 1
                item = normalize_entry(
                    entry,
                    feed_url=feed_url,
                    feed_source=feed_source,
                    fetched_at=fetched_at,
                    ticker_keywords=ticker_keywords,
                    focus_industries=industry_keywords,
                )
                if item is None:
                    result.entries_skipped_untagged += 1
                    continue
                if item.id in existing_ids:
                    result.entries_skipped_duplicate += 1
                    continue
                existing_ids.add(item.id)
                collected.append(item)

        result.new_items = collected
        logger.info(
            "News fetch complete: %d new, %d duplicates skipped, "
            "%d untagged skipped, %d feed(s) failed",
            result.new_count,
            result.entries_skipped_duplicate,
            result.entries_skipped_untagged,
            result.feeds_failed,
        )
        return result

    def run(
        self,
        repository: DataRepository,
        app_config: AppConfig,
        portfolio: Portfolio | None = None,
        focus_industries: list[str] | None = None,
    ) -> NewsFetchBatchResult:
        """Fetch feeds, merge into news_cache.json, and update bot state."""
        portfolio = portfolio or repository.load_portfolio()
        state = repository.load_state()
        cache = repository.load_news_cache()

        batch = self.fetch_batch(
            app_config,
            portfolio,
            state.latest_prices,
            cache,
            focus_industries,
        )

        updated_cache, _, total_items = merge_news_cache(
            cache,
            batch.new_items,
            max_items=app_config.news_max_items,
            retention_days=app_config.news_retention_days,
            now=batch.fetched_at,
        )
        repository.save_news_cache(updated_cache)

        state.last_news_fetch_at = batch.fetched_at
        repository.save_state(state)

        logger.info(
            "Updated news_cache.json with %d new article(s); total=%d",
            batch.new_count,
            total_items,
        )
        return batch


class NewsDataCollector(BaseCollector):
    """Scheduled collector that refreshes the news cache from RSS feeds."""

    name = "news_data"

    def __init__(self, service: NewsDataService | None = None) -> None:
        self._service = service or NewsDataService()

    def run(self, context: CollectorContext) -> CollectorResult:
        app_config = context.app_config
        feed_count = len([url for url in app_config.rss_feed_urls if url.strip()])

        if feed_count == 0:
            return CollectorResult(
                name=self.name,
                success=True,
                message="no RSS feeds configured",
            )

        batch = self._service.run(
            context.repository,
            app_config,
            context.portfolio,
            list(context.focus_industries) or None,
        )
        success = batch.feeds_failed < feed_count

        if batch.feeds_failed and batch.feeds_fetched:
            message = (
                f"added {batch.new_count} article(s) from "
                f"{batch.feeds_fetched}/{feed_count} feeds "
                f"({batch.feeds_failed} feed(s) failed)"
            )
        elif batch.feeds_failed:
            message = f"all {batch.feeds_failed} feed fetch(es) failed"
        else:
            message = (
                f"added {batch.new_count} article(s) from {batch.feeds_fetched} feed(s)"
            )

        return CollectorResult(
            name=self.name,
            success=success,
            message=message,
            finished_at=batch.fetched_at,
        )
