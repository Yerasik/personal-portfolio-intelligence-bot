"""Automatic per-ticker news discovery from yfinance, Google News RSS, and Finnhub."""

from __future__ import annotations

import hashlib
import logging
import re
from calendar import timegm
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from html import unescape
from typing import Any
from urllib.parse import quote_plus

import feedparser
import httpx
import yfinance as yf

from analysis.industries import build_news_focus_industries
from collectors.market_data import _quiet_yfinance, portfolio_tickers
from collectors.news_data import merge_news_cache, tag_sectors
from storage.models import NewsCache, NewsItem, TickerMetadata
from storage.repository import DataRepository

logger = logging.getLogger(__name__)

DEFAULT_FETCH_TIMEOUT_SECONDS = 30.0
FINNHUB_LOOKBACK_DAYS = 7


@dataclass(frozen=True)
class DiscoveredNewsItem:
    """Normalized article returned by AutoNewsDiscovery."""

    ticker: str
    title: str
    url: str
    source: str
    published_at: str
    summary: str

    def as_dict(self) -> dict[str, str]:
        return {
            "ticker": self.ticker,
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "published_at": self.published_at,
            "summary": self.summary,
        }


@dataclass
class AutoNewsDiscoveryResult:
    """Outcome of an auto news discovery run."""

    discovered: list[dict[str, str]] = field(default_factory=list)
    new_items_merged: int = 0
    total_cache_items: int = 0
    tickers_processed: int = 0
    fetched_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


def make_discovery_article_id(url: str, title: str) -> str:
    """Stable article id from URL and title for cross-source deduplication."""
    stable = f"{url.strip()}|{title.strip()}"
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]


def _dedup_key(url: str, title: str) -> str:
    return hashlib.sha256(f"{url.strip()}|{title.strip()}".encode("utf-8")).hexdigest()


def _to_iso8601(value: datetime | None) -> str:
    if value is None:
        return datetime.now(tz=UTC).isoformat()
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _parse_unix_timestamp(value: object | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _parse_feed_datetime(parsed: Any) -> datetime | None:
    if not parsed:
        return None
    try:
        return datetime.fromtimestamp(timegm(parsed), tz=UTC)
    except (OverflowError, OSError, TypeError, ValueError):
        return None


def _strip_html(text: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", text)
    return unescape(re.sub(r"\s+", " ", cleaned)).strip()


def _google_news_rss_url(ticker: str, company_name: str) -> str:
    query = quote_plus(f"{ticker} {company_name} stock")
    return (
        "https://news.google.com/rss/search"
        f"?q={query}&hl=en-US&gl=US&ceid=US:en"
    )


class AutoNewsDiscovery:
    """Discover portfolio-ticker news from multiple providers and merge into cache."""

    def __init__(
        self,
        repository: DataRepository,
        *,
        finnhub_api_key: str | None = None,
        max_workers: int = 3,
        timeout: float = DEFAULT_FETCH_TIMEOUT_SECONDS,
    ) -> None:
        self._repository = repository
        self._finnhub_api_key = (finnhub_api_key or "").strip() or None
        self._max_workers = max_workers
        self._timeout = timeout
        self._company_names: dict[str, str] = {}

    def ensure_company_names(self, tickers: list[str]) -> dict[str, str]:
        """Load cached company names and resolve any missing tickers via yfinance."""
        metadata = self._repository.load_ticker_metadata()
        names = dict(metadata.ticker_to_company_name)
        updated = False

        for ticker in tickers:
            cached = names.get(ticker, "").strip()
            if cached:
                continue
            names[ticker] = self._resolve_company_name(ticker)
            updated = True

        if updated:
            self._repository.save_ticker_metadata(
                TickerMetadata(
                    ticker_to_company_name=names,
                    updated_at=datetime.now(tz=UTC),
                )
            )

        self._company_names = names
        return names

    def discover_for_ticker(self, ticker: str, company_name: str | None = None) -> list[dict[str, str]]:
        """Fetch news for one ticker from all configured sources in parallel."""
        symbol = ticker.strip().upper()
        name = (company_name or self._company_names.get(symbol) or symbol).strip()
        collected: list[DiscoveredNewsItem] = []

        tasks = {
            "yfinance": lambda: self._fetch_yfinance(symbol),
            "google_news": lambda: self._fetch_google_news(symbol, name),
        }
        if self._finnhub_api_key:
            tasks["finnhub"] = lambda: self._fetch_finnhub(symbol)

        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            futures = {
                executor.submit(source_fn): source_name
                for source_name, source_fn in tasks.items()
            }
            for future in as_completed(futures):
                source_name = futures[future]
                try:
                    collected.extend(future.result())
                except Exception as exc:
                    logger.warning(
                        "Auto news source %s failed for %s: %s",
                        source_name,
                        symbol,
                        exc,
                    )

        deduped = self._deduplicate_items(collected)
        return [item.as_dict() for item in deduped.values()]

    def discover_all(self) -> list[dict[str, str]]:
        """Fetch and deduplicate news for every portfolio ticker."""
        portfolio = self._repository.load_portfolio()
        tickers = portfolio_tickers(portfolio)
        if not tickers:
            logger.info("Auto news discovery skipped: portfolio has no tickers")
            return []

        self.ensure_company_names(tickers)
        combined: dict[str, DiscoveredNewsItem] = {}

        for ticker in tickers:
            for item in self.discover_for_ticker(ticker, self._company_names.get(ticker)):
                key = _dedup_key(item["url"], item["title"])
                combined[key] = DiscoveredNewsItem(
                    ticker=item["ticker"],
                    title=item["title"],
                    url=item["url"],
                    source=item["source"],
                    published_at=item["published_at"],
                    summary=item.get("summary", ""),
                )

        logger.info(
            "Auto news discovery found %d unique article(s) across %d ticker(s)",
            len(combined),
            len(tickers),
        )
        return [item.as_dict() for item in combined.values()]

    def merge_into_cache(
        self,
        discovered: list[dict[str, str]],
        *,
        fetched_at: datetime | None = None,
    ) -> tuple[int, int]:
        """Convert discovered articles to NewsItem rows and merge into news_cache.json."""
        fetched_at = fetched_at or datetime.now(tz=UTC)
        app_config = self._repository.load_config()
        portfolio = self._repository.load_portfolio()
        ticker_industries = self._repository.load_ticker_industries()
        focus_industries = build_news_focus_industries(
            app_config.focus_industries,
            portfolio,
            ticker_industries.ticker_to_industry,
        )
        existing = self._repository.load_news_cache()
        existing_ids = {item.id for item in existing.items}
        news_items = [
            self._to_news_item(item, fetched_at=fetched_at, focus_industries=focus_industries)
            for item in discovered
        ]
        updated_cache, duplicates, total_items = merge_news_cache(
            existing,
            news_items,
            max_items=app_config.news_max_items,
            retention_days=app_config.news_retention_days,
            now=fetched_at,
        )
        self._repository.save_news_cache(updated_cache)
        new_count = sum(1 for item in news_items if item.id not in existing_ids)
        logger.info(
            "Auto news discovery merged %d new article(s) into news_cache.json "
            "(%d duplicate(s) skipped; total=%d)",
            new_count,
            duplicates,
            total_items,
        )
        return new_count, total_items

    def run(self) -> AutoNewsDiscoveryResult:
        """Discover portfolio news and persist new articles to news_cache.json."""
        fetched_at = datetime.now(tz=UTC)
        portfolio = self._repository.load_portfolio()
        tickers = portfolio_tickers(portfolio)
        discovered = self.discover_all()
        new_items, total_items = self.merge_into_cache(discovered, fetched_at=fetched_at)
        return AutoNewsDiscoveryResult(
            discovered=discovered,
            new_items_merged=new_items,
            total_cache_items=total_items,
            tickers_processed=len(tickers),
            fetched_at=fetched_at,
        )

    def _resolve_company_name(self, ticker: str) -> str:
        symbol = ticker.strip().upper()
        try:
            with _quiet_yfinance():
                info = yf.Ticker(symbol).info or {}
        except Exception as exc:
            logger.warning("Could not resolve company name for %s: %s", symbol, exc)
            return symbol

        for key in ("longName", "shortName", "symbol"):
            value = info.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return symbol

    def _deduplicate_items(
        self,
        items: list[DiscoveredNewsItem],
    ) -> dict[str, DiscoveredNewsItem]:
        unique: dict[str, DiscoveredNewsItem] = {}
        for item in items:
            key = _dedup_key(item.url, item.title)
            unique[key] = item
        return unique

    def _fetch_yfinance(self, ticker: str) -> list[DiscoveredNewsItem]:
        with _quiet_yfinance():
            raw_items = yf.Ticker(ticker).news or []

        discovered: list[DiscoveredNewsItem] = []
        for entry in raw_items:
            if not isinstance(entry, dict):
                continue
            title = str(entry.get("title", "")).strip()
            url = str(entry.get("link", "") or entry.get("url", "")).strip()
            if not title or not url:
                continue
            published_at = _parse_unix_timestamp(entry.get("providerPublishTime"))
            summary = str(entry.get("summary", "") or "").strip()
            source = str(entry.get("publisher", "") or "yfinance").strip() or "yfinance"
            discovered.append(
                DiscoveredNewsItem(
                    ticker=ticker,
                    title=title,
                    url=url,
                    source=source,
                    published_at=_to_iso8601(published_at),
                    summary=summary,
                )
            )
        return discovered

    def _fetch_google_news(self, ticker: str, company_name: str) -> list[DiscoveredNewsItem]:
        feed_url = _google_news_rss_url(ticker, company_name)
        with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
            response = client.get(feed_url)
            response.raise_for_status()
        feed = feedparser.parse(response.text)
        discovered: list[DiscoveredNewsItem] = []

        for entry in getattr(feed, "entries", []) or []:
            title = _strip_html(str(getattr(entry, "title", "") or "")).strip()
            url = str(getattr(entry, "link", "") or getattr(entry, "id", "")).strip()
            if not title or not url:
                continue
            summary = _strip_html(
                str(
                    getattr(entry, "summary", "")
                    or getattr(entry, "description", "")
                    or ""
                )
            )
            published_at = _parse_feed_datetime(
                getattr(entry, "published_parsed", None)
                or getattr(entry, "updated_parsed", None)
            )
            discovered.append(
                DiscoveredNewsItem(
                    ticker=ticker,
                    title=title,
                    url=url,
                    source="Google News",
                    published_at=_to_iso8601(published_at),
                    summary=summary,
                )
            )
        return discovered

    def _fetch_finnhub(self, ticker: str) -> list[DiscoveredNewsItem]:
        if not self._finnhub_api_key:
            return []

        today = datetime.now(tz=UTC).date()
        start = today - timedelta(days=FINNHUB_LOOKBACK_DAYS)
        params = {
            "symbol": ticker,
            "from": start.isoformat(),
            "to": today.isoformat(),
            "token": self._finnhub_api_key,
        }
        with httpx.Client(timeout=self._timeout) as client:
            response = client.get(
                "https://finnhub.io/api/v1/company-news",
                params=params,
            )
            response.raise_for_status()
            payload = response.json()

        if not isinstance(payload, list):
            logger.warning("Unexpected Finnhub response for %s: %r", ticker, payload)
            return []

        discovered: list[DiscoveredNewsItem] = []
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            title = str(entry.get("headline", "")).strip()
            url = str(entry.get("url", "")).strip()
            if not title or not url:
                continue
            published_at = _parse_unix_timestamp(entry.get("datetime"))
            summary = str(entry.get("summary", "") or "").strip()
            source = str(entry.get("source", "") or "Finnhub").strip() or "Finnhub"
            discovered.append(
                DiscoveredNewsItem(
                    ticker=ticker,
                    title=title,
                    url=url,
                    source=source,
                    published_at=_to_iso8601(published_at),
                    summary=summary,
                )
            )
        return discovered

    def _to_news_item(
        self,
        item: dict[str, str],
        *,
        fetched_at: datetime,
        focus_industries: list[str],
    ) -> NewsItem:
        ticker = item["ticker"].strip().upper()
        title = item["title"].strip()
        url = item["url"].strip()
        summary = item.get("summary", "").strip()
        published_raw = item.get("published_at", "").strip()
        published_at: datetime | None = None
        if published_raw:
            try:
                published_at = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
            except ValueError:
                published_at = None

        tag_text = " ".join(part for part in (title, summary) if part)
        return NewsItem(
            id=make_discovery_article_id(url, title),
            title=title,
            source=item.get("source", "").strip(),
            url=url,
            published_at=published_at,
            fetched_at=fetched_at,
            ticker_tags=[ticker],
            sector_tags=tag_sectors(tag_text, focus_industries),
            summary=summary[:500],
        )
