#!/usr/bin/env python3
"""Smoke tests for ordinary-user portfolio change notifications."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.commands import BotCommands
from config.settings import RuntimeSettings
from storage.models import AppConfig, BotUser, BotUsers, Portfolio, Position, TickerStrategy
from storage.paths import resolve_data_paths
from storage.portfolio_ops import PortfolioTickerResult
from storage.repository import DataRepository


def run_test() -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="portfolio-notify-test-"))
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
        repository.save_portfolio(Portfolio(positions=[Position(ticker="AAPL", shares=10)]))
        repository.upsert_ticker_strategy(
            "AAPL",
            developer_reasoning="internal",
            strategy_text="Hold for ecosystem strength.",
            shares_at_add=10,
            strategy_text_by_language={"en": "Hold for ecosystem strength."},
        )

        settings = RuntimeSettings(
            telegram_bot_token="test-token",
            telegram_chat_id="111",
        )
        commands = BotCommands(repository=repository, llm=object(), settings=settings)  # type: ignore[arg-type]
        sent_messages: list[dict] = []

        def _mock_post(url: str, json: dict):
            sent_messages.append(json)

            class Response:
                def raise_for_status(self) -> None:
                    return None

                def json(self) -> dict:
                    return {"ok": True}

            return Response()

        with patch("bot.notifier.httpx.Client") as mock_client_cls, patch.object(
            commands,
            "_deliver_alerts_after_portfolio_change",
        ):
            mock_client = mock_client_cls.return_value
            mock_client.__enter__.return_value = mock_client
            mock_client.post.side_effect = _mock_post

            with patch.object(
                repository,
                "add_ticker_to_portfolio",
                return_value=PortfolioTickerResult(
                    True,
                    "Added 2 share(s) to AAPL; now holding 12 share(s).",
                    "AAPL",
                    is_new_position=False,
                ),
            ):
                add_reply = commands.add_ticker_message(111, "AAPL", 2.0)
                add_message = add_reply.text

            remove_reply = commands.remove_ticker_message(111, "MSFT")
            remove_message = remove_reply.text
            edit_message = commands.edit_strategy_message(
                111,
                "AAPL",
                "Updated thesis for ordinary users.",
            )

        if "Notified" not in add_message and "user" not in add_message.lower():
            raise AssertionError(f"add_ticker should report notification: {add_message}")

        texts = [payload["text"] for payload in sent_messages]
        if not any("Portfolio update" in text or "Обновление портфеля" in text for text in texts):
            raise AssertionError("ordinary user should receive portfolio update")
        if not any("Investment idea updated" in text or "обновлена" in text.lower() for text in texts):
            raise AssertionError("ordinary user should receive strategy update on edit")

        repository.save_portfolio(Portfolio(positions=[Position(ticker="MSFT", shares=5)]))
        sent_messages.clear()
        with patch("bot.notifier.httpx.Client") as mock_client_cls, patch.object(
            commands,
            "_deliver_alerts_after_portfolio_change",
        ):
            mock_client = mock_client_cls.return_value
            mock_client.__enter__.return_value = mock_client
            mock_client.post.side_effect = _mock_post
            remove_reply = commands.remove_ticker_message(111, "MSFT")
            remove_message = remove_reply.text

        if "Notified" not in remove_message and "user" not in remove_message.lower():
            raise AssertionError(f"remove_ticker should report notification: {remove_message}")
        if not sent_messages:
            raise AssertionError("remove_ticker should notify ordinary user")

        print("Portfolio notification checks passed.")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
