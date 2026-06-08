"""Telegram notification delivery for scheduled alerts and summaries."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx

from analysis.llm import LlmAdvisoryResult, LlmClient
from analysis.news_summarizer import NewsSummary, summarize_news
from analysis.rules import AlertCandidate
from bot.formatter import format_daily_summary, format_urgent_alert
from config.settings import RuntimeSettings
from storage.models import AppConfig, BotUser, SentAlertRecord
from storage.repository import DataRepository

logger = logging.getLogger(__name__)

TELEGRAM_API_TIMEOUT_SECONDS = 30.0


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

    def deliver_urgent_alerts(
        self,
        alerts: list[AlertCandidate],
        repository: DataRepository,
        app_config: AppConfig,
    ) -> AlertDeliveryResult:
        """Send unsent urgent alerts to all users and record deliveries in state."""
        if not self.is_configured:
            logger.warning("Telegram notifier not configured; skipping alert delivery")
            return AlertDeliveryResult(skipped=len(alerts))

        users = self._authorized_users(repository)
        if not users:
            logger.warning("No authorized users; skipping alert delivery")
            return AlertDeliveryResult(skipped=len(alerts))

        urgent_alerts = [alert for alert in alerts if alert.urgency == "urgent"]
        if not urgent_alerts:
            logger.info("No urgent alerts to deliver")
            return AlertDeliveryResult()

        state = repository.load_state()
        now = datetime.now(tz=UTC)
        cooldown = timedelta(hours=app_config.alert_suppression_hours)
        recent_ids, recent_keys = _recent_sent_keys(state.last_sent_alerts, now, cooldown)

        result = AlertDeliveryResult()
        for alert in urgent_alerts:
            if alert.id in recent_ids:
                logger.info(
                    "Skipping urgent alert id=%s key=%s (id cooldown active)",
                    alert.id,
                    alert.alert_key,
                )
                result.skipped += 1
                continue
            if alert.alert_key in recent_keys:
                logger.info(
                    "Skipping urgent alert id=%s key=%s (key cooldown active)",
                    alert.id,
                    alert.alert_key,
                )
                result.skipped += 1
                continue

            delivery_failed = False
            for user in users:
                message = format_urgent_alert(alert, lang=user.language)
                try:
                    self.send_text(user.chat_id, message)
                except Exception as exc:
                    logger.exception(
                        "Failed to send urgent alert id=%s key=%s to chat_id=%s: %s",
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
            recent_ids.add(alert.id)
            recent_keys.add(alert.alert_key)
            result.sent += 1
            logger.info(
                "Delivered urgent alert id=%s key=%s to %d user(s)",
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
            "Urgent alert delivery finished: sent=%d skipped=%d failed=%d",
            result.sent,
            result.skipped,
            result.failed,
        )
        return result

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
        delivered = False
        for user in users:
            lang = user.language
            message = format_daily_summary(
                portfolio,
                alerts,
                advisory_by_language.get(lang),
                app_config,
                news_summary=summaries.get(lang),
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

    if not app_config.enable_llm_summaries:
        for lang in languages:
            advisory_by_language[lang] = None
            news_summary_by_language[lang] = None
        return advisory_by_language, news_summary_by_language

    for lang in languages:
        advisory_by_language[lang] = llm.synthesize_advisory(
            portfolio,
            app_config,
            state,
            news_cache,
            alerts,
            ticker_to_industry=ticker_to_industry,
            language=lang,
        )
        news_summary_by_language[lang] = summarize_news(
            llm,
            portfolio,
            app_config,
            news_cache,
            ticker_to_industry,
            company_names=company_names,
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
