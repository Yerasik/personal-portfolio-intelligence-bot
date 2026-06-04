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
    alert_price_change_pct: float = Field(default=5.0, gt=0)
    enable_llm_summaries: bool = False


class PendingAlert(BaseModel):
    """An alert queued for Telegram delivery."""

    id: str
    severity: Literal["info", "warning", "urgent"]
    message: str
    created_at: datetime
    related_tickers: list[str] = Field(default_factory=list)


class BotState(BaseModel):
    """Operational state persisted in state.json."""

    last_digest_at: datetime | None = None
    last_market_fetch_at: datetime | None = None
    last_news_fetch_at: datetime | None = None
    pending_alerts: list[PendingAlert] = Field(default_factory=list)


class NewsItem(BaseModel):
    """A cached news article linked to tickers or sectors."""

    id: str
    title: str
    url: str
    source: str = ""
    published_at: datetime | None = None
    fetched_at: datetime
    related_tickers: list[str] = Field(default_factory=list)
    summary: str = ""


class NewsCache(BaseModel):
    """Cached news feed persisted in news_cache.json."""

    items: list[NewsItem] = Field(default_factory=list)
    updated_at: datetime | None = None
