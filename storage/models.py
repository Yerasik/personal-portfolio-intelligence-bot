"""Pydantic models for JSON documents stored under /app/data."""

from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator


class PositionLot(BaseModel):
    """One purchase lot for a portfolio holding."""

    shares: float = Field(gt=0)
    cost: float | None = Field(default=None, gt=0)
    date: str = "unknown"


class Position(BaseModel):
    """A single portfolio holding with per-lot cost tracking."""

    ticker: str = Field(min_length=1)
    lots: list[PositionLot] = Field(default_factory=list)
    notes: str = ""

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_format(cls, data: Any) -> Any:
        """Convert legacy shares/cost_basis rows into a single lot on load."""
        if not isinstance(data, dict):
            return data
        if data.get("lots"):
            cleaned = {key: value for key, value in data.items() if key not in {"shares", "cost_basis"}}
            return cleaned

        shares = data.pop("shares", None)
        cost_basis = data.pop("cost_basis", None)
        if shares is None:
            return data

        lot: dict[str, Any] = {
            "shares": shares,
            "date": "unknown",
        }
        if cost_basis is not None:
            lot["cost"] = cost_basis
        data["lots"] = [lot]
        return data

    @model_validator(mode="after")
    def validate_lots(self) -> Self:
        if not self.lots:
            raise ValueError("position must have at least one lot")
        if self.shares <= 0:
            raise ValueError("total shares must be positive")
        return self

    @property
    def shares(self) -> float:
        """Total shares across all lots."""
        return sum(lot.shares for lot in self.lots)

    @property
    def blended_cost_basis(self) -> float | None:
        """Weighted average cost per share from lots with a known cost."""
        priced = [lot for lot in self.lots if lot.cost is not None]
        if not priced:
            return None
        total_shares = sum(lot.shares for lot in priced)
        if total_shares <= 0:
            return None
        weighted = sum(lot.shares * lot.cost for lot in priced if lot.cost is not None)
        return weighted / total_shares

    @property
    def cost_basis(self) -> float | None:
        """Backward-compatible alias for blended_cost_basis."""
        return self.blended_cost_basis

    def total_cost_in_listing_currency(self) -> float | None:
        """Sum of lot shares × cost for lots with a known per-share cost."""
        priced = [
            lot.shares * lot.cost
            for lot in self.lots
            if lot.cost is not None
        ]
        if not priced:
            return None
        return sum(priced)


class Portfolio(BaseModel):
    """User portfolio persisted in portfolio.json."""

    positions: list[Position] = Field(default_factory=list)
    cash: float = Field(default=0.0, ge=0, description="HKD cash balance")
    cash_usd: float = Field(default=0.0, ge=0, description="USD cash balance")
    cash_jpy: float = Field(default=0.0, ge=0, description="JPY cash balance")
    notes: str = ""


UserRole = Literal["developer", "ordinary"]


class BotUser(BaseModel):
    """Authorized Telegram user with language and role."""

    chat_id: int
    language: str = "en"
    role: UserRole = "ordinary"

    @field_validator("language")
    @classmethod
    def _normalize_language(cls, value: str) -> str:
        from storage.languages import normalize_language

        return normalize_language(value)


class BotUsers(BaseModel):
    """Access control list persisted in users.json."""

    users: list[BotUser] = Field(default_factory=list)


class TickerIndustryMap(BaseModel):
    """Static mapping from ticker symbols to industry labels."""

    ticker_to_industry: dict[str, str] = Field(default_factory=dict)


class TickerMetadata(BaseModel):
    """Cached company names resolved from market data providers."""

    ticker_to_company_name: dict[str, str] = Field(default_factory=dict)
    updated_at: datetime | None = None


class TickerStrategy(BaseModel):
    """Investment rationale for a portfolio holding."""

    ticker: str
    developer_reasoning: str
    strategy_text: str
    strategy_text_by_language: dict[str, str] = Field(default_factory=dict)
    shares_at_add: float | None = None
    holding_horizon: Literal["long", "short"] = "long"
    created_at: datetime
    updated_at: datetime


class TickerStrategies(BaseModel):
    """Per-ticker investment ideas persisted in ticker_strategies.json."""

    by_ticker: dict[str, TickerStrategy] = Field(default_factory=dict)


class TickerSentimentSignal(BaseModel):
    """Cached sentiment score for one ticker."""

    score: float
    updated_at: datetime
    article_count: int


class TickerProsConsMemo(BaseModel):
    """Cached pros/cons memo for one ticker."""

    memo: str
    generated_at: datetime
    source: Literal["llm", "fallback"]


class SignalsFile(BaseModel):
    """Derived signals persisted in signals.json."""

    sentiment: dict[str, TickerSentimentSignal] = Field(default_factory=dict)
    pros_cons: dict[str, TickerProsConsMemo] = Field(default_factory=dict)
    pros_cons_last_sentiment: dict[str, float] = Field(default_factory=dict)


class PositionPerformancePoint(BaseModel):
    """Per-ticker price and market value at one snapshot."""

    price: float
    value: float


class PortfolioPerformanceSnapshot(BaseModel):
    """Timestamped portfolio valuation record."""

    timestamp: datetime
    total_value: float
    total_cost: float
    daily_pnl_pct: float
    cash_hkd: float | None = None
    positions: dict[str, PositionPerformancePoint] = Field(default_factory=dict)


class PerformanceHistory(BaseModel):
    """Append-only portfolio valuation history."""

    snapshots: list[PortfolioPerformanceSnapshot] = Field(default_factory=list)


class RiskProfile(BaseModel):
    """Client risk tolerance limits for /analyze portfolio risk."""

    max_annual_volatility_pct: float = Field(default=18.0, gt=0, le=100)
    max_drawdown_pct: float = Field(default=20.0, gt=0, le=100)
    max_single_holding_pct: float = Field(default=30.0, gt=0, le=100)
    risk_metric_primary: Literal["volatility", "composite"] = "volatility"
    volatility_lookback_months: int = Field(default=6, ge=1, le=24)
    include_sentiment_in_score: bool = True


class AppConfig(BaseModel):
    """Bot behavior and watch settings persisted in config.json."""

    timezone: str = "Asia/Hong_Kong"
    digest_hour: int = Field(default=8, ge=0, le=23)
    digest_minute: int = Field(default=0, ge=0, le=59)
    focus_industries: list[str] = Field(default_factory=list)
    sector_keywords: dict[str, list[str]] = Field(default_factory=dict)
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
    market_fetch_interval_minutes: int = Field(default=30, ge=5, le=1440)
    news_fetch_interval_minutes: int = Field(default=60, ge=5, le=1440)
    auto_news_interval_minutes: int = Field(default=30, ge=5, le=1440)
    rule_evaluation_interval_minutes: int = Field(default=60, ge=5, le=1440)
    sentiment_analysis_interval_minutes: int = Field(default=60, ge=5, le=1440)
    pros_cons_interval_hours: int = Field(default=4, ge=1, le=168)
    sentiment_alert_threshold: float = Field(default=0.3, gt=0, le=2.0)
    enable_sector_attention_alerts: bool = False
    macro_sector_label: str = "Macro & Central Banks"
    daily_summary_top_headlines: int = Field(default=5, ge=1, le=15)
    enable_daily_summary: bool = True
    enable_weekly_summary: bool = True
    weekly_summary_hour: int = Field(default=8, ge=0, le=23)
    weekly_summary_minute: int = Field(default=0, ge=0, le=59)
    performance_history_retention_days: int = Field(default=31, ge=7, le=365)
    performance_chart_period: Literal["week", "month", "all"] = "month"
    deep_digest_times: list[str] = Field(default_factory=lambda: ["06:00", "20:00"])
    enable_deep_digest: bool = True
    deep_digest_recipients: Literal["developers", "all_users"] = "developers"
    risk_profile: RiskProfile = Field(default_factory=RiskProfile)
    benchmark_ticker: str = "SPY"
    ollama_base_url: str = ""
    ollama_model: str = ""
    enable_llm_summaries: bool = False


class PendingAlert(BaseModel):
    """An alert queued for Telegram delivery."""

    id: str
    type: str = ""
    severity: Literal["info", "warning", "urgent"]
    message: str
    created_at: datetime
    related_tickers: list[str] = Field(default_factory=list)
    industry: str | None = None
    llm_explanation: str | None = None
    details: dict[str, str | int | float] = Field(default_factory=dict)


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


class EvaluatedAlertRecord(BaseModel):
    """Recently evaluated rule alert used for duplicate suppression."""

    alert_key: str
    evaluated_at: datetime


DeveloperPortfolioActionType = Literal["sell", "add_ticker", "remove_ticker", "deposit_cash"]
DeveloperPortfolioActionStatus = Literal["pending_confirm", "completed"]


class DeveloperPortfolioAction(BaseModel):
    """Developer portfolio edit awaiting confirm or available for undo."""

    action_id: str
    status: DeveloperPortfolioActionStatus
    action_type: DeveloperPortfolioActionType
    created_at: datetime
    developer_chat_id: int
    portfolio_before: Portfolio
    strategy_snapshots: dict[str, TickerStrategy] = Field(default_factory=dict)
    payload: dict[str, str | float | bool | None] = Field(default_factory=dict)
    users_notified: int = 0


class BotState(BaseModel):
    """Operational state persisted in state.json."""

    last_digest_at: datetime | None = None
    last_weekly_summary_at: datetime | None = None
    digest_sent_at: datetime | None = None
    deep_digest_price_snapshot: dict[str, float] = Field(default_factory=dict)
    deep_digest_sentiment_snapshot: dict[str, float] = Field(default_factory=dict)
    last_market_fetch_at: datetime | None = None
    last_news_fetch_at: datetime | None = None
    latest_prices: dict[str, MarketQuote] = Field(default_factory=dict)
    last_sent_alerts: list[SentAlertRecord] = Field(default_factory=list)
    last_evaluated_alerts: list[EvaluatedAlertRecord] = Field(default_factory=list)
    pending_alerts: list[PendingAlert] = Field(default_factory=list)
    price_alert_regime: dict[str, Literal["drop", "rise"]] = Field(default_factory=dict)
    developer_portfolio_action: DeveloperPortfolioAction | None = None


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
