"""Pydantic models for JSON documents stored under /app/data."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Position(BaseModel):
    """A single portfolio holding."""

    ticker: str = Field(min_length=1)
    shares: float = Field(gt=0)
    cost_basis: float | None = None
    notes: str = ""


class Portfolio(BaseModel):
    """User portfolio persisted in portfolio.json."""

    positions: list[Position] = Field(default_factory=list)
    notes: str = ""


class AppConfig(BaseModel):
    """Bot behavior and watch settings persisted in config.json."""

    timezone: str = "Asia/Hong_Kong"
    digest_hour: int = Field(default=8, ge=0, le=23)
    digest_minute: int = Field(default=0, ge=0, le=59)
    focus_industries: list[str] = Field(default_factory=list)
    extra_watchlist: list[str] = Field(default_factory=list)
    rss_feed_urls: list[str] = Field(default_factory=list)
    news_max_items: int = Field(default=500, ge=50, le=5000)
    news_retention_days: int = Field(default=14, ge=1, le=90)
    alert_price_change_pct: float = Field(default=5.0, gt=0)
    alert_negative_news_count: int = Field(default=3, ge=2, le=20)
    alert_negative_news_window_hours: int = Field(default=24, ge=1, le=168)
    alert_sector_article_count: int = Field(default=3, ge=2, le=20)
    alert_sector_window_hours: int = Field(default=24, ge=1, le=168)
    alert_suppression_hours: int = Field(default=12, ge=1, le=168)
    enable_llm_summaries: bool = False


class PendingAlert(BaseModel):
    """An alert queued for Telegram delivery."""

    id: str
    severity: Literal["info", "warning", "urgent"]
    message: str
    created_at: datetime
    related_tickers: list[str] = Field(default_factory=list)


class MarketQuote(BaseModel):
    """Latest market snapshot for a single ticker."""

    ticker: str
    price: float | None = None
    change_pct: float | None = None
    volume: int | None = None
    company_name: str = ""
    sector: str = ""
    industry: str = ""
    currency: str = ""
    fetched_at: datetime


class SentAlertRecord(BaseModel):
    """Recently sent rule alert used for duplicate suppression."""

    alert_key: str
    alert_id: str
    sent_at: datetime


class BotState(BaseModel):
    """Operational state persisted in state.json."""

    last_digest_at: datetime | None = None
    last_market_fetch_at: datetime | None = None
    last_news_fetch_at: datetime | None = None
    latest_prices: dict[str, MarketQuote] = Field(default_factory=dict)
    last_sent_alerts: list[SentAlertRecord] = Field(default_factory=list)
    pending_alerts: list[PendingAlert] = Field(default_factory=list)


class NewsItem(BaseModel):
    """A cached news article linked to tickers or sectors."""

    id: str
    title: str
    source: str = ""
    url: str
    published_at: datetime | None = None
    fetched_at: datetime
    ticker_tags: list[str] = Field(default_factory=list)
    sector_tags: list[str] = Field(default_factory=list)
    sentiment: float | None = None
    importance: float | None = None
    processed: bool = False
    alert_sent: bool = False
    summary: str = ""


class NewsCache(BaseModel):
    """Cached news feed persisted in news_cache.json."""

    items: list[NewsItem] = Field(default_factory=list)
    updated_at: datetime | None = None
