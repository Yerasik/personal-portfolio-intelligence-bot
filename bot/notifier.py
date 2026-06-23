"""Telegram notification delivery for scheduled alerts and summaries."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from collections.abc import Callable

import httpx

from analysis.llm import LlmAdvisoryResult, LlmClient
from analysis.move_explainer import explain_price_move, recent_news_titles_for_ticker
from analysis.news_summarizer import NewsSummary, summarize_daily_news_brief, summarize_news
from analysis.rules import AlertCandidate
from bot.formatter import (
    format_daily_summary,
    format_informational_alert,
    format_portfolio_change_notification,
    format_sell_announcement,
    format_strategy_announcement,
    format_strategy_update_notification,
    format_urgent_alert,
    truncate_message,
)
from config.settings import RuntimeSettings
from storage.models import AppConfig, BotState, BotUser, NewsCache, SentAlertRecord
from storage.repository import DataRepository

logger = logging.getLogger(__name__)

TELEGRAM_API_TIMEOUT_SECONDS = 30.0
_PRICE_MOVE_ALERT_TYPES = frozenset({"price_drop", "price_rise"})
_PUSHABLE_ALERT_URGENCIES = frozenset({"warning", "urgent"})


@dataclass
class AlertDeliveryResult:
    """Outcome of a Telegram alert delivery pass."""

    sent: int = 0
    skipped: int = 0
    failed: int = 0


class TelegramNotifier:
    """Send formatted messages to all authorized Telegram users."""

    def __init__(self, settings: RuntimeSettings) -> None:
        self._token = settings.telegram_bot_token.strip()

    @property
    def is_configured(self) -> bool:
        return bool(self._token)

    def send_text(self, chat_id: int | str, text: str) -> None:
        """Send a plain-text message via the Telegram Bot API."""
        if not self.is_configured:
            raise RuntimeError("Telegram notifier is not configured")

        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        payload = {
            "chat_id": str(chat_id),
            "text": text,
            "disable_web_page_preview": True,
        }

        with httpx.Client(timeout=TELEGRAM_API_TIMEOUT_SECONDS) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()

        body = response.json()
        if not isinstance(body, dict) or not body.get("ok"):
            raise RuntimeError(f"Telegram API returned failure: {body!r}")

    def _authorized_users(self, repository: DataRepository) -> list[BotUser]:
        return repository.load_users().users

    def deliver_alerts(
        self,
        alerts: list[AlertCandidate],
        repository: DataRepository,
        app_config: AppConfig,
        *,
        llm: LlmClient | None = None,
        state: BotState | None = None,
        news_cache: NewsCache | None = None,
    ) -> AlertDeliveryResult:
        """Send unsent warning and urgent alerts to all users and record deliveries."""
        if not self.is_configured:
            logger.warning("Telegram notifier not configured; skipping alert delivery")
            return AlertDeliveryResult(skipped=len(alerts))

        users = self._authorized_users(repository)
        if not users:
            logger.warning("No authorized users; skipping alert delivery")
            return AlertDeliveryResult(skipped=len(alerts))

        pushable_alerts = [
            alert
            for alert in alerts
            if alert.urgency in _PUSHABLE_ALERT_URGENCIES
            and (
                app_config.enable_sector_attention_alerts
                or alert.type != "sector_attention"
            )
        ]
        if not pushable_alerts:
            logger.info("No warning or urgent alerts to deliver")
            return AlertDeliveryResult()

        state = repository.load_state()
        now = datetime.now(tz=UTC)
        cooldown = timedelta(hours=app_config.alert_suppression_hours)
        recent_ids, recent_keys = _recent_sent_keys(state.last_sent_alerts, now, cooldown)

        result = AlertDeliveryResult()
        for alert in pushable_alerts:
            if alert.id in recent_ids:
                logger.info(
                    "Skipping alert id=%s key=%s (id cooldown active)",
                    alert.id,
                    alert.alert_key,
                )
                result.skipped += 1
                continue
            if alert.alert_key in recent_keys:
                logger.info(
                    "Skipping alert id=%s key=%s (key cooldown active)",
                    alert.id,
                    alert.alert_key,
                )
                result.skipped += 1
                continue

            delivery_failed = False
            explanation_by_lang: dict[str, str] = {}
            for user in users:
                llm_explanation: str | None = None
                if (
                    app_config.enable_llm_summaries
                    and llm is not None
                    and state is not None
                    and news_cache is not None
                    and alert.type in _PRICE_MOVE_ALERT_TYPES
                    and alert.ticker
                ):
                    if user.language not in explanation_by_lang:
                        quote = state.latest_prices.get(alert.ticker)
                        if quote is not None and quote.change_pct is not None:
                            news = recent_news_titles_for_ticker(news_cache, alert.ticker)
                            explanation_by_lang[user.language] = explain_price_move(
                                llm,
                                alert.ticker,
                                quote.change_pct,
                                "today",
                                news,
                                company_name=quote.company_name,
                                sector=quote.sector,
                                language=user.language,
                            ).to_message(user.language)
                    llm_explanation = explanation_by_lang.get(user.language)

                if alert.urgency == "urgent":
                    message = format_urgent_alert(
                        alert,
                        lang=user.language,
                        llm_explanation=llm_explanation,
                    )
                else:
                    message = format_informational_alert(alert, lang=user.language)
                    if llm_explanation:
                        message = truncate_message(f"{message}\n\n{llm_explanation}")
                try:
                    self.send_text(user.chat_id, message)
                except Exception as exc:
                    logger.exception(
                        "Failed to send alert id=%s key=%s to chat_id=%s: %s",
                        alert.id,
                        alert.alert_key,
                        user.chat_id,
                        exc,
                    )
                    delivery_failed = True

            if delivery_failed:
                result.failed += 1
                continue

            state.last_sent_alerts.append(
                SentAlertRecord(
                    alert_key=alert.alert_key,
                    alert_id=alert.id,
                    sent_at=now,
                )
            )
            if alert.type == "price_drop" and alert.ticker:
                state.price_alert_regime[alert.ticker] = "drop"
            elif alert.type == "price_rise" and alert.ticker:
                state.price_alert_regime[alert.ticker] = "rise"
            recent_ids.add(alert.id)
            recent_keys.add(alert.alert_key)
            result.sent += 1
            logger.info(
                "Delivered %s alert id=%s key=%s to %d user(s)",
                alert.urgency,
                alert.id,
                alert.alert_key,
                len(users),
            )

        state.last_sent_alerts = _prune_sent_alerts(
            state.last_sent_alerts,
            now,
            app_config.alert_suppression_hours,
        )
        repository.save_state(state)

        logger.info(
            "Alert delivery finished: sent=%d skipped=%d failed=%d",
            result.sent,
            result.skipped,
            result.failed,
        )
        return result

    def deliver_urgent_alerts(
        self,
        alerts: list[AlertCandidate],
        repository: DataRepository,
        app_config: AppConfig,
        *,
        llm: LlmClient | None = None,
        state: BotState | None = None,
        news_cache: NewsCache | None = None,
    ) -> AlertDeliveryResult:
        """Backward-compatible alias for deliver_alerts."""
        return self.deliver_alerts(
            alerts,
            repository,
            app_config,
            llm=llm,
            state=state,
            news_cache=news_cache,
        )

    def deliver_daily_summary(
        self,
        *,
        portfolio,
        alerts: list[AlertCandidate],
        advisory_by_language: dict[str, LlmAdvisoryResult | None],
        app_config: AppConfig,
        repository: DataRepository,
        news_summary_by_language: dict[str, NewsSummary | None] | None = None,
    ) -> bool:
        """Send the daily summary message to each authorized user in their language."""
        if not self.is_configured:
            logger.warning("Telegram notifier not configured; skipping daily summary send")
            return False

        users = self._authorized_users(repository)
        if not users:
            logger.warning("No authorized users; skipping daily summary send")
            return False

        summaries = news_summary_by_language or {}
        state = repository.load_state()
        news_cache = repository.load_news_cache()
        ticker_to_industry = repository.load_ticker_industries().ticker_to_industry
        delivered = False
        for user in users:
            lang = user.language
            message = format_daily_summary(
                portfolio,
                alerts,
                advisory_by_language.get(lang),
                app_config,
                news_summary=summaries.get(lang),
                state=state,
                news_cache=news_cache,
                ticker_to_industry=ticker_to_industry,
                lang=lang,
            )
            try:
                self.send_text(user.chat_id, message)
            except Exception:
                logger.exception(
                    "Failed to send daily summary to chat_id=%s",
                    user.chat_id,
                )
                continue
            delivered = True
            logger.info("Daily summary delivered to chat_id=%s (lang=%s)", user.chat_id, lang)

        return delivered

    def deliver_deep_digest(
        self,
        repository: DataRepository,
        messages_by_language: dict[str, str],
        *,
        recipients: str = "developers",
    ) -> bool:
        """Send the deep digest to developers (default) or all authorized users."""
        if not self.is_configured:
            logger.warning("Telegram notifier not configured; skipping deep digest send")
            return False

        if recipients == "all_users":
            users = self._authorized_users(repository)
        else:
            users = self._developer_users(repository)

        if not users:
            logger.warning("No deep digest recipients; skipping send")
            return False

        delivered = False
        for user in users:
            message = messages_by_language.get(user.language)
            if not message:
                message = messages_by_language.get("en", "")
            if not message:
                continue
            try:
                self.send_text(user.chat_id, truncate_message(message))
            except Exception:
                logger.exception(
                    "Failed to send deep digest to chat_id=%s",
                    user.chat_id,
                )
                continue
            delivered = True
            logger.info(
                "Deep digest delivered to chat_id=%s (lang=%s)",
                user.chat_id,
                user.language,
            )

        return delivered

    def _developer_users(self, repository: DataRepository) -> list[BotUser]:
        return [
            user
            for user in self._authorized_users(repository)
            if user.role == "developer"
        ]

    def _ordinary_users(self, repository: DataRepository) -> list[BotUser]:
        return [
            user
            for user in self._authorized_users(repository)
            if user.role == "ordinary"
        ]

    def notify_ordinary_users(
        self,
        repository: DataRepository,
        *,
        build_message: Callable[[str], str],
    ) -> int:
        """Send a per-language message to every ordinary user."""
        if not self.is_configured:
            logger.warning("Telegram notifier not configured; skipping user notification")
            return 0

        ordinary_users = self._ordinary_users(repository)
        if not ordinary_users:
            return 0

        sent = 0
        for user in ordinary_users:
            message = build_message(user.language)
            try:
                self.send_text(user.chat_id, message)
            except Exception:
                logger.exception(
                    "Failed to send portfolio notification to chat_id=%s",
                    user.chat_id,
                )
                continue
            sent += 1
            logger.info(
                "Portfolio notification delivered to chat_id=%s (lang=%s)",
                user.chat_id,
                user.language,
            )
        return sent

    def notify_portfolio_change(
        self,
        repository: DataRepository,
        *,
        change: str,
        symbol: str,
        shares: float = 0.0,
    ) -> int:
        """Tell ordinary users when the developer changes portfolio holdings."""
        return self.notify_ordinary_users(
            repository,
            build_message=lambda lang: format_portfolio_change_notification(
                change=change,  # type: ignore[arg-type]
                symbol=symbol,
                shares=shares,
                lang=lang,
            ),
        )

    def notify_strategy_content(
        self,
        repository: DataRepository,
        *,
        symbol: str,
        text_for_language: Callable[[str], str],
    ) -> int:
        """Tell ordinary users when a stored investment idea changes."""
        return self.notify_ordinary_users(
            repository,
            build_message=lambda lang: format_strategy_update_notification(
                symbol,
                text_for_language(lang),
                lang=lang,
            ),
        )

    def notify_new_ticker_strategy(
        self,
        repository: DataRepository,
        ticker: str,
        shares: float,
        *,
        llm: LlmClient,
        app_config: AppConfig,
        strategy_text: str,
        announcement_en: str,
        state: BotState,
        strategy_text_by_language: dict[str, str] | None = None,
    ) -> int:
        """Alert ordinary users when a developer adds a new holding with a strategy."""
        if not self.is_configured:
            logger.warning("Telegram notifier not configured; skipping strategy notification")
            return 0

        users = self._ordinary_users(repository)
        if not users:
            return 0

        symbol = ticker.strip().upper()
        quote = state.latest_prices.get(symbol)
        company_name = quote.company_name if quote is not None else ""
        localized_strategy = strategy_text_by_language or {}
        announcements_by_lang: dict[str, str] = {"en": announcement_en}
        sent = 0

        for user in users:
            lang = user.language
            if lang not in announcements_by_lang:
                from analysis.strategy_writer import generate_strategy_announcement

                source_text = localized_strategy.get(lang) or localized_strategy.get(
                    "en", strategy_text
                )
                if lang == "en":
                    announcements_by_lang[lang] = announcement_en
                else:
                    announcements_by_lang[lang] = generate_strategy_announcement(
                        llm,
                        symbol,
                        source_text,
                        shares=shares,
                        company_name=company_name,
                        language=lang,
                        enabled=app_config.enable_llm_summaries,
                    )

            message = format_strategy_announcement(
                symbol,
                shares,
                announcements_by_lang[lang],
                lang=lang,
            )
            try:
                self.send_text(user.chat_id, message)
            except Exception:
                logger.exception(
                    "Failed to send strategy announcement for %s to chat_id=%s",
                    symbol,
                    user.chat_id,
                )
                continue
            sent += 1
            logger.info(
                "Strategy announcement for %s delivered to chat_id=%s (lang=%s)",
                symbol,
                user.chat_id,
                lang,
            )

        return sent

    def notify_ticker_sold(
        self,
        repository: DataRepository,
        ticker: str,
        *,
        shares_sold: float,
        sell_price: float,
        fully_sold: bool,
        llm: LlmClient,
        app_config: AppConfig,
        announcement_en: str,
        state: BotState,
    ) -> int:
        """Alert ordinary users when the developer sells shares."""
        if not self.is_configured:
            logger.warning("Telegram notifier not configured; skipping sell notification")
            return 0

        users = self._ordinary_users(repository)
        if not users:
            return 0

        symbol = ticker.strip().upper()
        quote = state.latest_prices.get(symbol)
        company_name = quote.company_name if quote is not None else ""
        announcements_by_lang: dict[str, str] = {"en": announcement_en}
        sent = 0

        for user in users:
            lang = user.language
            if lang not in announcements_by_lang:
                from analysis.strategy_writer import generate_sell_announcement

                if lang == "en":
                    announcements_by_lang[lang] = announcement_en
                else:
                    announcements_by_lang[lang] = generate_sell_announcement(
                        llm,
                        symbol,
                        announcement_en,
                        shares_sold=shares_sold,
                        sell_price=sell_price,
                        company_name=company_name,
                        language=lang,
                        enabled=app_config.enable_llm_summaries,
                    )

            message = format_sell_announcement(
                symbol,
                shares_sold,
                announcements_by_lang[lang],
                fully_sold=fully_sold,
                lang=lang,
            )
            try:
                self.send_text(user.chat_id, message)
            except Exception:
                logger.exception(
                    "Failed to send sell announcement for %s to chat_id=%s",
                    symbol,
                    user.chat_id,
                )
                continue
            sent += 1
            logger.info(
                "Sell announcement for %s delivered to chat_id=%s (lang=%s)",
                symbol,
                user.chat_id,
                lang,
            )

        return sent


def build_localized_daily_content(
    *,
    llm: LlmClient,
    portfolio,
    app_config: AppConfig,
    state,
    news_cache,
    alerts: list[AlertCandidate],
    ticker_to_industry: dict[str, str],
    company_names: dict[str, str],
    languages: set[str],
) -> tuple[dict[str, LlmAdvisoryResult | None], dict[str, NewsSummary | None]]:
    """Build advisory and news summaries once per distinct user language."""
    advisory_by_language: dict[str, LlmAdvisoryResult | None] = {}
    news_summary_by_language: dict[str, NewsSummary | None] = {}

    for lang in languages:
        if app_config.enable_llm_summaries:
            advisory_by_language[lang] = llm.synthesize_advisory(
                portfolio,
                app_config,
                state,
                news_cache,
                alerts,
                ticker_to_industry=ticker_to_industry,
                language=lang,
            )
        else:
            advisory_by_language[lang] = None
        news_summary_by_language[lang] = summarize_daily_news_brief(
            llm,
            portfolio,
            app_config,
            news_cache,
            ticker_to_industry,
            company_names=company_names,
            enabled=app_config.enable_llm_summaries,
            language=lang,
        )

    return advisory_by_language, news_summary_by_language


def _recent_sent_keys(
    records: list[SentAlertRecord],
    now: datetime,
    cooldown: timedelta,
) -> tuple[set[str], set[str]]:
    recent_ids: set[str] = set()
    recent_keys: set[str] = set()
    for record in records:
        if now - record.sent_at > cooldown:
            continue
        recent_ids.add(record.alert_id)
        recent_keys.add(record.alert_key)
    return recent_ids, recent_keys


def _prune_sent_alerts(
    records: list[SentAlertRecord],
    now: datetime,
    suppression_hours: int,
) -> list[SentAlertRecord]:
    retention = timedelta(hours=max(suppression_hours * 4, 24))
    cutoff = now - retention
    return [record for record in records if record.sent_at >= cutoff]
