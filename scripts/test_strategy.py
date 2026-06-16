#!/usr/bin/env python3
"""Smoke test for ticker strategy storage and commands."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.strategy_writer import GeneratedStrategy
from bot.commands import BotCommands
from config.settings import RuntimeSettings
from storage.models import AppConfig, BotUser, BotUsers, Portfolio, Position
from storage.paths import resolve_data_paths
from storage.portfolio_ops import PortfolioTickerResult
from storage.repository import DataRepository


def run_test() -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="strategy-test-"))
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
        repository.save_config(AppConfig(enable_llm_summaries=True))
        repository.save_portfolio(Portfolio(positions=[]))

        settings = RuntimeSettings(
            telegram_bot_token="test-token",
            telegram_chat_id="111",
        )
        commands = BotCommands(repository=repository, llm=object(), settings=settings)  # type: ignore[arg-type]

        generated = GeneratedStrategy(
            strategy_text="English thesis for ordinary users.",
            announcement_text="TEST added: AI infrastructure exposure.",
        )
        localized = {
            "en": "English thesis for ordinary users.",
            "ru": "Русская инвестиционная идея для пользователей.",
        }

        with patch.object(
            repository,
            "add_ticker_to_portfolio",
            return_value=PortfolioTickerResult(
                True,
                "Added TEST (1 share(s)) to the portfolio.",
                "TEST",
                is_new_position=True,
            ),
        ), patch(
            "bot.commands.build_strategy_text_by_language",
            return_value=(generated, localized),
        ), patch.object(
            commands,
            "_deliver_alerts_after_portfolio_change",
        ), patch("bot.notifier.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.__enter__.return_value = mock_client

            class Response:
                def raise_for_status(self) -> None:
                    return None

                def json(self) -> dict:
                    return {"ok": True}

            mock_client.post.return_value = Response()
            add_message = commands.add_ticker_strategy_message(
                111,
                "TEST",
                1.0,
                "Developer raw notes about the idea.",
            )

        if "TEST" not in add_message or "1 user" not in add_message.lower():
            raise AssertionError(f"unexpected add message: {add_message}")

        stored = repository.get_ticker_strategy("TEST")
        if stored is None or stored.strategy_text_by_language.get("ru") != localized["ru"]:
            raise AssertionError("localized strategy was not persisted")

        repository.save_portfolio(
            Portfolio(positions=[Position(ticker="TEST", shares=1.0)])
        )
        list_message = commands.strategy_message(222)
        if "TEST" not in list_message or "Русская инвестиционная" not in list_message:
            raise AssertionError(f"strategy list not localized: {list_message}")

        detail = commands.strategy_message(222, ticker="TEST")
        if "Русская инвестиционная" not in detail:
            raise AssertionError(f"strategy detail not localized: {detail}")
        if "Developer notes" in detail:
            raise AssertionError("ordinary user should not see developer notes")

        dev_detail = commands.strategy_message(111, ticker="TEST")
        if "Developer notes" not in dev_detail:
            raise AssertionError("developer should see internal notes")
        if "English thesis" not in dev_detail:
            raise AssertionError("developer should see English cached strategy")

        with patch.object(
            commands,
            "_deliver_alerts_after_portfolio_change",
        ), patch("bot.notifier.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.__enter__.return_value = mock_client

            class Response:
                def raise_for_status(self) -> None:
                    return None

                def json(self) -> dict:
                    return {"ok": True}

            mock_client.post.return_value = Response()
            edit_message = commands.edit_strategy_message(
                111,
                "TEST",
                "Hard rewritten strategy text for everyone.",
            )

        if "updated" not in edit_message.lower():
            raise AssertionError(f"edit failed: {edit_message}")

        updated = repository.get_ticker_strategy("TEST")
        if updated is None or updated.strategy_text != "Hard rewritten strategy text for everyone.":
            raise AssertionError("strategy text was not overwritten")

        with patch(
            "bot.commands.localized_strategy_text",
            return_value="Переведённая стратегия для пользователей.",
        ) as translate_mock:
            translated_detail = commands.strategy_message(222, ticker="TEST")
        if "Переведённая стратегия" not in translated_detail:
            raise AssertionError("on-demand translation was not shown")
        if not translate_mock.called:
            raise AssertionError("expected on-demand translation after edit")

        print("Strategy command checks passed.")

        repository.save_portfolio(
            Portfolio(positions=[Position(ticker="HOLD", shares=201.0)])
        )
        generated_hold = GeneratedStrategy(
            strategy_text="Updated thesis without changing shares.",
            announcement_text="",
        )
        with patch.object(
            repository,
            "add_ticker_to_portfolio",
        ) as add_mock, patch(
            "bot.commands.build_strategy_text_by_language",
            return_value=(generated_hold, {"en": generated_hold.strategy_text}),
        ), patch.object(
            commands,
            "_deliver_alerts_after_portfolio_change",
        ), patch.object(
            commands,
            "_notifier",
        ) as notifier_factory:
            notifier_factory.return_value.notify_strategy_content.return_value = 0
            commands.add_ticker_strategy_message(
                111,
                "HOLD",
                None,
                "Reasoning that should not add shares.",
            )

        if add_mock.called:
            raise AssertionError("add_ticker_to_portfolio must not run for existing holdings")
        loaded = repository.load_portfolio()
        hold = next(p for p in loaded.positions if p.ticker == "HOLD")
        if hold.shares != 201.0:
            raise AssertionError(f"shares changed unexpectedly: {hold.shares}")

        print("Existing-holding strategy checks passed.")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
