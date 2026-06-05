"""Deterministic rules for alerts and recommendations.

Example alert candidates produced by this module:

    AlertCandidate(
        id="a1b2c3d4e5f67890",
        type="price_drop",
        ticker="AAPL",
        industry=None,
        urgency="warning",
        title="AAPL down 6.2% today",
        explanation="AAPL fell 6.20% since the last market fetch, breaching the 5.0% drop threshold.",
        created_at=datetime(2026, 6, 4, 9, 30, tzinfo=UTC),
    )

    AlertCandidate(
        id="b2c3d4e5f6789012",
        type="repeated_negative_news",
        ticker="TSLA",
        industry=None,
        urgency="urgent",
        title="Repeated negative news for TSLA",
        explanation="3 negative articles tagged to TSLA were found in the last 24 hour(s).",
        created_at=datetime(2026, 6, 4, 9, 30, tzinfo=UTC),
    )

    AlertCandidate(
        id="c3d4e5f678901234",
        type="sector_attention",
        ticker=None,
        industry="Consumer Electronics",
        urgency="warning",
        title="Sector attention: Consumer Electronics",
        explanation="4 articles tagged to Consumer Electronics were found in the last 24 hour(s).",
        created_at=datetime(2026, 6, 4, 9, 30, tzinfo=UTC),
    )
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from collectors.market_data import portfolio_tickers
from storage.models import AppConfig, BotState, MarketQuote, NewsCache, NewsItem, Portfolio

logger = logging.getLogger(__name__)

AlertType = Literal[
    "price_drop",
    "price_rise",
    "repeated_negative_news",
    "sector_attention",
]
AlertUrgency = Literal["info", "warning", "urgent"]

_NEGATIVE_NEWS_KEYWORDS = (
    "bankruptcy",
    "decline",
    "downgrade",
    "drop",
    "fall",
    "fraud",
    "lawsuit",
    "layoff",
    "loss",
    "miss",
    "plunge",
    "recall",
    "slump",
    "warning",
)


@dataclass(frozen=True)
class AlertCandidate:
    """Normalized alert produced by the rules engine before delivery."""

    id: str
    type: AlertType
    ticker: str | None
    industry: str | None
    urgency: AlertUrgency
    title: str
    explanation: str
    created_at: datetime

    @property
    def alert_key(self) -> str:
        """Stable deduplication key for duplicate suppression."""
        ticker = self.ticker or ""
        industry = self.industry or ""
        return f"{self.type}:{ticker}:{industry}"


@dataclass(frozen=True)
class RulesEngine:
    """Evaluate portfolio and market changes without LLM inference."""

    app_config: AppConfig

    def evaluate(
        self,
        portfolio: Portfolio,
        state: BotState,
        news_cache: NewsCache,
        now: datetime | None = None,
    ) -> list[AlertCandidate]:
        """Return alert candidates after applying duplicate suppression."""
        evaluated_at = now or datetime.now(tz=UTC)
        candidates: list[AlertCandidate] = []
        candidates.extend(self._price_drop_alerts(state, evaluated_at))
        candidates.extend(self._price_rise_alerts(state, evaluated_at))
        candidates.extend(
            self._repeated_negative_news_alerts(portfolio, news_cache, evaluated_at)
        )
        candidates.extend(self._sector_attention_alerts(news_cache, evaluated_at))

        suppressed = self._suppress_duplicates(candidates, state, evaluated_at)
        logger.info(
            "Rules evaluation produced %d candidate(s); %d suppressed as duplicates",
            len(suppressed),
            len(candidates) - len(suppressed),
        )
        return suppressed

    def _tracked_tickers(self, portfolio: Portfolio) -> list[str]:
        """Portfolio tickers plus any symbols from extra_watchlist in config."""
        tickers = portfolio_tickers(portfolio)
        for symbol in self.app_config.extra_watchlist:
            normalized = symbol.strip().upper()
            if normalized and normalized not in tickers:
                tickers.append(normalized)
        return tickers

    def _price_drop_alerts(
        self,
        state: BotState,
        evaluated_at: datetime,
    ) -> list[AlertCandidate]:
        """Alert when a cached quote dropped beyond alert_price_change_pct."""
        threshold = self.app_config.alert_price_change_pct
        alerts: list[AlertCandidate] = []

        for symbol, quote in state.latest_prices.items():
            if quote.change_pct is None or quote.change_pct > -threshold:
                continue

            change_pct = quote.change_pct
            urgency = self._urgency_for_price_move(change_pct, threshold)
            title = f"{symbol} down {abs(change_pct):.1f}% today"
            explanation = (
                f"{symbol} fell {abs(change_pct):.2f}% since the last market fetch, "
                f"breaching the {threshold:.1f}% drop threshold."
            )
            alerts.append(
                self._build_alert(
                    alert_type="price_drop",
                    ticker=symbol,
                    industry=None,
                    urgency=urgency,
                    title=title,
                    explanation=explanation,
                    created_at=evaluated_at,
                )
            )

        return alerts

    def _price_rise_alerts(
        self,
        state: BotState,
        evaluated_at: datetime,
    ) -> list[AlertCandidate]:
        """Alert when a cached quote rose beyond alert_price_change_pct."""
        threshold = self.app_config.alert_price_change_pct
        alerts: list[AlertCandidate] = []

        for symbol, quote in state.latest_prices.items():
            if quote.change_pct is None or quote.change_pct < threshold:
                continue

            change_pct = quote.change_pct
            urgency: AlertUrgency = (
                "warning" if change_pct >= threshold * 2 else "info"
            )
            title = f"{symbol} up {change_pct:.1f}% today"
            explanation = (
                f"{symbol} rose {change_pct:.2f}% since the last market fetch, "
                f"breaching the {threshold:.1f}% rise threshold."
            )
            alerts.append(
                self._build_alert(
                    alert_type="price_rise",
                    ticker=symbol,
                    industry=None,
                    urgency=urgency,
                    title=title,
                    explanation=explanation,
                    created_at=evaluated_at,
                )
            )

        return alerts

    def _repeated_negative_news_alerts(
        self,
        portfolio: Portfolio,
        news_cache: NewsCache,
        evaluated_at: datetime,
    ) -> list[AlertCandidate]:
        """Alert when many negative articles tag the same ticker in a time window."""
        window = timedelta(hours=self.app_config.alert_negative_news_window_hours)
        minimum = self.app_config.alert_negative_news_count
        alerts: list[AlertCandidate] = []

        for symbol in self._tracked_tickers(portfolio):
            articles = [
                item
                for item in news_cache.items
                if symbol in item.ticker_tags and self._is_negative_news(item)
            ]
            recent = self._articles_in_window(articles, evaluated_at, window)
            if len(recent) < minimum:
                continue

            urgency: AlertUrgency = "urgent" if len(recent) >= minimum + 1 else "warning"
            title = f"Repeated negative news for {symbol}"
            explanation = (
                f"{len(recent)} negative articles tagged to {symbol} were found in "
                f"the last {self.app_config.alert_negative_news_window_hours} hour(s)."
            )
            alerts.append(
                self._build_alert(
                    alert_type="repeated_negative_news",
                    ticker=symbol,
                    industry=None,
                    urgency=urgency,
                    title=title,
                    explanation=explanation,
                    created_at=evaluated_at,
                )
            )

        return alerts

    def _sector_attention_alerts(
        self,
        news_cache: NewsCache,
        evaluated_at: datetime,
    ) -> list[AlertCandidate]:
        """Alert when a focus industry gets unusually many news articles."""
        window = timedelta(hours=self.app_config.alert_sector_window_hours)
        minimum = self.app_config.alert_sector_article_count
        alerts: list[AlertCandidate] = []

        for industry in self.app_config.focus_industries:
            label = industry.strip()
            if not label:
                continue

            articles = [
                item for item in news_cache.items if label in item.sector_tags
            ]
            recent = self._articles_in_window(articles, evaluated_at, window)
            if len(recent) < minimum:
                continue

            urgency: AlertUrgency = "warning" if len(recent) >= minimum + 1 else "info"
            title = f"Sector attention: {label}"
            explanation = (
                f"{len(recent)} articles tagged to {label} were found in the last "
                f"{self.app_config.alert_sector_window_hours} hour(s)."
            )
            alerts.append(
                self._build_alert(
                    alert_type="sector_attention",
                    ticker=None,
                    industry=label,
                    urgency=urgency,
                    title=title,
                    explanation=explanation,
                    created_at=evaluated_at,
                )
            )

        return alerts

    def _suppress_duplicates(
        self,
        candidates: list[AlertCandidate],
        state: BotState,
        evaluated_at: datetime,
    ) -> list[AlertCandidate]:
        """Drop alerts whose alert_key was already sent within the cooldown window."""
        suppression_window = timedelta(hours=self.app_config.alert_suppression_hours)
        recent_keys = {
            record.alert_key
            for record in state.last_sent_alerts
            if evaluated_at - record.sent_at <= suppression_window
        }

        kept: list[AlertCandidate] = []
        for candidate in candidates:
            if candidate.alert_key in recent_keys:
                logger.debug("Suppressing duplicate alert %s", candidate.alert_key)
                continue
            kept.append(candidate)
        return kept

    def _build_alert(
        self,
        *,
        alert_type: AlertType,
        ticker: str | None,
        industry: str | None,
        urgency: AlertUrgency,
        title: str,
        explanation: str,
        created_at: datetime,
    ) -> AlertCandidate:
        """Build an AlertCandidate with a stable dedup key and short id hash."""
        alert_key = f"{alert_type}:{ticker or ''}:{industry or ''}"
        alert_id = hashlib.sha256(
            f"{alert_key}:{created_at.isoformat()}".encode("utf-8")
        ).hexdigest()[:16]
        return AlertCandidate(
            id=alert_id,
            type=alert_type,
            ticker=ticker,
            industry=industry,
            urgency=urgency,
            title=title,
            explanation=explanation,
            created_at=created_at,
        )

    def _urgency_for_price_move(
        self,
        change_pct: float,
        threshold: float,
    ) -> AlertUrgency:
        """Escalate to urgent when the drop is at least 2× the configured threshold."""
        if change_pct <= -threshold * 2:
            return "urgent"
        return "warning"

    def _articles_in_window(
        self,
        articles: list[NewsItem],
        evaluated_at: datetime,
        window: timedelta,
    ) -> list[NewsItem]:
        """Keep only articles published/fetched within the given time window."""
        cutoff = evaluated_at - window
        recent: list[NewsItem] = []
        for item in articles:
            timestamp = item.published_at or item.fetched_at
            if timestamp >= cutoff:
                recent.append(item)
        return recent

    def _is_negative_news(self, item: NewsItem) -> bool:
        """Detect negative sentiment via score or keyword matching in title/summary."""
        if item.sentiment is not None:
            return item.sentiment < 0

        text = f"{item.title} {item.summary}".lower()
        return any(re.search(rf"\b{re.escape(keyword)}\b", text) for keyword in _NEGATIVE_NEWS_KEYWORDS)
