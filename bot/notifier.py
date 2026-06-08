"""Telegram notification delivery for scheduled alerts and summaries."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx

from analysis.llm import LlmAdvisoryResult
from analysis.news_summarizer import NewsSummary
from analysis.rules import AlertCandidate
from bot.formatter import format_daily_summary, format_urgent_alert
from config.settings import RuntimeSettings
from storage.models import AppConfig, SentAlertRecord
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
    """Send formatted messages to the configured single-user Telegram chat."""

    def __init__(self, settings: RuntimeSettings) -> None:
        self._token = settings.telegram_bot_token
        self._chat_id = str(settings.telegram_chat_id).strip()

    @property
    def is_configured(self) -> bool:
        return bool(self._token and self._chat_id)

    def send_text(self, text: str) -> None:
        """Send a plain-text message via the Telegram Bot API."""
        if not self.is_configured:
            raise RuntimeError("Telegram notifier is not configured")

        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }

        with httpx.Client(timeout=TELEGRAM_API_TIMEOUT_SECONDS) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()

        body = response.json()
        if not isinstance(body, dict) or not body.get("ok"):
            raise RuntimeError(f"Telegram API returned failure: {body!r}")

    def deliver_urgent_alerts(
        self,
        alerts: list[AlertCandidate],
        repository: DataRepository,
        app_config: AppConfig,
    ) -> AlertDeliveryResult:
        """Send unsent urgent alerts and record successful deliveries in state."""
        if not self.is_configured:
            logger.warning("Telegram notifier not configured; skipping alert delivery")
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

            message = format_urgent_alert(alert)
            try:
                self.send_text(message)
            except Exception as exc:
                logger.exception(
                    "Failed to send urgent alert id=%s key=%s: %s",
                    alert.id,
                    alert.alert_key,
                    exc,
                )
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
                "Delivered urgent alert id=%s key=%s to chat_id=%s",
                alert.id,
                alert.alert_key,
                self._chat_id,
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
        advisory: LlmAdvisoryResult | None,
        app_config: AppConfig,
        repository: DataRepository,
        news_summary: NewsSummary | None = None,
    ) -> bool:
        """Send the daily summary message to Telegram."""
        if not self.is_configured:
            logger.warning("Telegram notifier not configured; skipping daily summary send")
            return False

        message = format_daily_summary(
            portfolio,
            alerts,
            advisory,
            app_config,
            news_summary=news_summary,
        )
        try:
            self.send_text(message)
        except Exception:
            logger.exception("Failed to send daily summary to Telegram")
            return False

        logger.info("Daily summary delivered to chat_id=%s", self._chat_id)
        return True


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
