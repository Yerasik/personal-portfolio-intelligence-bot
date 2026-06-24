#!/usr/bin/env python3
"""Smoke tests for /sell_ticker confirm and undo flow."""

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
from bot.sell_args import parse_sell_args
from config.settings import RuntimeSettings
from storage.models import AppConfig, BotUser, BotUsers, Portfolio, Position
from storage.paths import resolve_data_paths
from storage.repository import DataRepository


def run_test() -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="sell-ticker-test-"))
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
            Portfolio(positions=[Position(ticker="NVDA", shares=10, cost_basis=120.0)])
        )
        repository.upsert_ticker_strategy(
            "NVDA",
            developer_reasoning="internal",
            strategy_text="AI infrastructure holding.",
            shares_at_add=10,
            strategy_text_by_language={"en": "AI infrastructure holding."},
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

        portfolio = repository.load_portfolio()
        parsed, err = parse_sell_args(
            ["NVDA", "150.25", "Taking profits after earnings run-up"],
            portfolio,
        )
        if err is not None or parsed is None:
            raise AssertionError(f"parse failed: {err}")

        with patch("bot.notifier.httpx.Client") as mock_client_cls, patch.object(
            commands,
            "_deliver_alerts_after_portfolio_change",
        ):
            mock_client = mock_client_cls.return_value
            mock_client.__enter__.return_value = mock_client
            mock_client.post.side_effect = _mock_post

            preview = commands.prepare_sell_ticker(111, parsed)
            if preview.reply_markup is None:
                raise AssertionError("sell should require confirmation")
            action = repository.get_developer_portfolio_action()
            if action is None or action.status != "pending_confirm":
                raise AssertionError("pending sell action not stored")

            confirm = commands.confirm_developer_portfolio_action(111, action.action_id)
            if "Cash balance" not in confirm.text:
                raise AssertionError(f"developer should see cash balance: {confirm.text}")
            if confirm.reply_markup is None:
                raise AssertionError("confirm should offer undo")

        if not sent_messages:
            raise AssertionError("ordinary user should be notified")

        texts = [payload["text"] for payload in sent_messages]
        if not any("Position sold" in text or "Позиция продана" in text for text in texts):
            raise AssertionError(f"expected sell announcement, got: {texts}")

        loaded = repository.load_portfolio()
        if loaded.positions:
            raise AssertionError("full sell should remove position")
        if loaded.cash != 1502.5:
            raise AssertionError(f"unexpected cash balance: {loaded.cash}")

        action = repository.get_developer_portfolio_action()
        if action is None or action.status != "completed":
            raise AssertionError("completed action should be stored for undo")

        sent_messages.clear()
        with patch("bot.notifier.httpx.Client") as mock_client_cls, patch.object(
            commands,
            "_deliver_alerts_after_portfolio_change",
        ):
            mock_client = mock_client_cls.return_value
            mock_client.__enter__.return_value = mock_client
            mock_client.post.side_effect = _mock_post
            undo = commands.undo_developer_portfolio_action(111, action.action_id)

        if "Undone" not in undo.text and "undone" not in undo.text.lower():
            raise AssertionError(f"undo should succeed: {undo.text}")
        correction_texts = [payload["text"] for payload in sent_messages]
        if not any(
            "Correction" in text or "Исправление" in text for text in correction_texts
        ):
            raise AssertionError(
                f"users should receive correction notice: {correction_texts}"
            )

        restored = repository.load_portfolio()
        if not restored.positions or restored.positions[0].ticker != "NVDA":
            raise AssertionError("undo should restore NVDA position")
        if restored.cash != 0:
            raise AssertionError(f"cash should be restored to 0, got {restored.cash}")
        if repository.get_ticker_strategy("NVDA") is None:
            raise AssertionError("strategy should be restored after undo")

        print("Sell ticker checks passed.")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
