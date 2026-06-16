#!/usr/bin/env python3
"""Smoke test for portfolio strategy broadcast helper."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from datetime import UTC, datetime

from bot.strategy_broadcast import notify_portfolio_strategies
from config.settings import RuntimeSettings
from storage.models import AppConfig, BotUser, BotUsers, Portfolio, Position, TickerStrategy, TickerStrategies
from storage.paths import resolve_data_paths
from storage.repository import DataRepository

NOW = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)


def run_test() -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="strategy-broadcast-test-"))
    print(f"Using temp data dir: {temp_dir}")

    try:
        paths = resolve_data_paths(temp_dir)
        repository = DataRepository(paths)
        repository.save_users(
            BotUsers(
                users=[
                    BotUser(chat_id=111, language="en", role="developer"),
                    BotUser(chat_id=222, language="ru", role="ordinary"),
                ]
            )
        )
        repository.save_config(AppConfig(enable_llm_summaries=False))
        repository.save_portfolio(
            Portfolio(
                positions=[
                    Position(ticker="VRT", shares=3.0),
                    Position(ticker="ZZZZ", shares=1.0),
                ]
            )
        )
        repository.save_ticker_strategies(
            TickerStrategies(
                by_ticker={
                    "VRT": TickerStrategy(
                        ticker="VRT",
                        developer_reasoning="internal",
                        strategy_text="Data center infrastructure thesis.",
                        strategy_text_by_language={
                            "en": "Data center infrastructure thesis.",
                            "ru": "Тезис по инфраструктуре дата-центров.",
                        },
                        shares_at_add=3.0,
                        created_at=NOW,
                        updated_at=NOW,
                    )
                }
            )
        )

        settings = RuntimeSettings(
            telegram_bot_token="test-token",
            telegram_chat_id="111",
        )
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

            from bot.notifier import TelegramNotifier

            report = notify_portfolio_strategies(
                repository,
                TelegramNotifier(settings),  # type: ignore[arg-type]
                object(),  # type: ignore[arg-type]
                app_config=repository.load_config(),
            )

        if report.notified_total != 1:
            raise AssertionError(f"expected 1 delivery, got {report.notified_total}")
        if "ZZZZ" not in report.skipped_tickers:
            raise AssertionError("missing strategy ticker should be skipped")
        if len(sent_messages) != 1:
            raise AssertionError(f"expected one Telegram payload, got {len(sent_messages)}")
        if "обновлена" not in sent_messages[0]["text"].lower():
            raise AssertionError("Russian user should receive localized strategy body")

        dry_report = notify_portfolio_strategies(
            repository,
            TelegramNotifier(settings),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            app_config=repository.load_config(),
            dry_run=True,
        )
        if dry_report.notified_total != 1:
            raise AssertionError("dry run should count planned deliveries")

        print("Strategy broadcast checks passed.")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
