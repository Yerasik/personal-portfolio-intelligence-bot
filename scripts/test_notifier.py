#!/usr/bin/env python3
"""Smoke test for Telegram alert delivery and formatters."""

from __future__ import annotations

import shutil
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.rules import AlertCandidate
from bot.formatter import format_daily_summary, format_informational_alert, format_urgent_alert
from bot.notifier import TelegramNotifier
from storage.models import AppConfig, BotUser, BotUsers, Portfolio, Position, SentAlertRecord
from storage.paths import resolve_data_paths
from storage.repository import DataRepository

NOW = datetime(2026, 6, 4, 12, 0, tzinfo=UTC)


def _urgent_alert() -> AlertCandidate:
    return AlertCandidate(
        id="urgent123",
        type="price_drop",
        ticker="AAPL",
        industry=None,
        urgency="urgent",
        title="AAPL down 8.0% today",
        explanation="AAPL fell 8.00% since the last market fetch.",
        created_at=NOW,
    )


def _info_alert() -> AlertCandidate:
    return AlertCandidate(
        id="info456",
        type="price_rise",
        ticker="MSFT",
        industry=None,
        urgency="info",
        title="MSFT up 6.0% today",
        explanation="MSFT rose 6.00% since the last market fetch.",
        created_at=NOW,
    )


class SettingsStub:
    telegram_bot_token = "test-token"


def _warning_alert() -> AlertCandidate:
    return AlertCandidate(
        id="warn789",
        type="price_drop",
        ticker="NVDA",
        industry=None,
        urgency="warning",
        title="NVDA down 3.0% today",
        explanation="NVDA fell 3.00% since the last market fetch.",
        created_at=NOW,
    )


def run_test() -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="notifier-test-"))
    print(f"Using temp data dir: {temp_dir}")

    try:
        urgent_text = format_urgent_alert(_urgent_alert(), lang="en")
        info_text = format_informational_alert(_info_alert(), lang="en")
        summary_text = format_daily_summary(
            Portfolio(positions=[Position(ticker="AAPL", shares=1)]),
            [_urgent_alert()],
            None,
            AppConfig(),
            lang="de",
        )
        for text in (urgent_text, info_text, summary_text):
            if "{" in text and "}" in text:
                raise AssertionError("formatted message looks like raw JSON/dict")
        if "Tägliche Portfolio-Zusammenfassung" not in summary_text:
            raise AssertionError("German daily summary header missing")

        paths = resolve_data_paths(temp_dir)
        repository = DataRepository(paths)
        repository.save_config(AppConfig(alert_suppression_hours=12))
        repository.save_users(
            BotUsers(
                users=[
                    BotUser(chat_id=111, language="en", role="developer"),
                    BotUser(chat_id=222, language="de", role="ordinary"),
                ]
            )
        )

        notifier = TelegramNotifier(SettingsStub())  # type: ignore[arg-type]
        sent_messages: list[dict] = []

        def _mock_post(url: str, json: dict):
            sent_messages.append(json)

            class Response:
                def raise_for_status(self) -> None:
                    return None

                def json(self) -> dict:
                    return {"ok": True}

            return Response()

        with patch("bot.notifier.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.__enter__.return_value = mock_client
            mock_client.post.side_effect = _mock_post

            first = notifier.deliver_alerts(
                [_urgent_alert()],
                repository,
                repository.load_config(),
            )
            second = notifier.deliver_alerts(
                [_urgent_alert()],
                repository,
                repository.load_config(),
            )
            warning_delivery = notifier.deliver_alerts(
                [_warning_alert()],
                repository,
                repository.load_config(),
            )

        if first.sent != 1 or first.skipped != 0:
            raise AssertionError(f"expected first delivery to send 1 alert, got {first}")
        if second.sent != 0 or second.skipped != 1:
            raise AssertionError(f"expected second delivery to skip cooldown, got {second}")
        if warning_delivery.sent != 1:
            raise AssertionError(f"expected warning alert delivery, got {warning_delivery}")
        if len(sent_messages) != 4:
            raise AssertionError(f"expected four Telegram payloads, got {len(sent_messages)}")
        if "URGENT ALERT" not in sent_messages[0]["text"]:
            raise AssertionError("English user should receive English labels")
        if "DRINGENDE WARNUNG" not in sent_messages[1]["text"]:
            raise AssertionError("German user should receive German labels")

        state = repository.load_state()
        if len(state.last_sent_alerts) != 2:
            raise AssertionError(
                f"expected two sent alert records after delivery, got {len(state.last_sent_alerts)}"
            )

        print("Urgent alert message:\n", urgent_text)
        print("Informational alert message:\n", info_text)
        print("Daily summary message:\n", summary_text)
        print("Sent payloads:", len(sent_messages))
        print("Notifier checks passed.")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
