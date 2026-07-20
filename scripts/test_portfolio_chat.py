#!/usr/bin/env python3
"""Smoke tests for portfolio-aware chat and LLM provider selection."""

from __future__ import annotations

import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.llm import LlmClient, LlmGenerationError
from analysis.portfolio_chat import build_portfolio_chat_prompt
from bot.commands import BotCommands
from config.settings import RuntimeSettings
from storage.models import (
    AppConfig,
    BotState,
    BotUser,
    BotUsers,
    MarketQuote,
    NewsCache,
    NewsItem,
    Portfolio,
    Position,
    normalize_llm_provider,
)
from storage.paths import resolve_data_paths
from storage.repository import DataRepository

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


def test_normalize_provider() -> None:
    if normalize_llm_provider("ollama") != "ollama":
        raise AssertionError("ollama alias failed")
    if normalize_llm_provider("Claude") != "claude":
        raise AssertionError("claude alias failed")
    if normalize_llm_provider("openai") != "gpt":
        raise AssertionError("openai should map to gpt")
    if normalize_llm_provider("nope") is not None:
        raise AssertionError("invalid provider should be None")


def test_default_provider_and_set_llm() -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="chat-llm-"))
    try:
        paths = resolve_data_paths(temp_dir)
        repository = DataRepository(paths)
        repository.save_users(
            BotUsers(users=[BotUser(chat_id=111, language="en", role="ordinary")])
        )
        user = repository.find_user(111)
        assert user is not None
        if user.llm_provider != "ollama":
            raise AssertionError("default llm_provider should be ollama")

        ok, provider = repository.set_user_llm_provider(111, "claude")
        if not ok or provider != "claude":
            raise AssertionError("set_user_llm_provider failed")
        user = repository.find_user(111)
        assert user is not None
        if user.llm_provider != "claude":
            raise AssertionError("provider not persisted")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_chat_prompt_includes_context() -> None:
    portfolio = Portfolio(
        positions=[Position(ticker="AAPL", shares=10)],
        cash=1000.0,
    )
    config = AppConfig(focus_industries=["Consumer Electronics"])
    state = BotState(
        latest_prices={
            "AAPL": MarketQuote(
                ticker="AAPL",
                price=180.0,
                change_pct=-3.5,
                volume=1000,
                company_name="Apple Inc.",
                fetched_at=NOW,
            )
        }
    )
    news_cache = NewsCache(
        items=[
            NewsItem(
                id="n1",
                title="Apple supply chain update",
                source="Test",
                url="https://example.com/n1",
                published_at=NOW,
                fetched_at=NOW,
                ticker_tags=["AAPL"],
                sector_tags=["Consumer Electronics"],
            )
        ]
    )
    prompt = build_portfolio_chat_prompt(
        user_message="How is AAPL doing today?",
        portfolio=portfolio,
        app_config=config,
        state=state,
        news_cache=news_cache,
        history=[],
    )
    for needle in (
        "AAPL",
        "Apple Inc.",
        "-3.50%",
        "Apple supply chain update",
        "How is AAPL doing today?",
        "HKD: 1000",
    ):
        if needle not in prompt:
            raise AssertionError(f"prompt missing {needle!r}")


def test_chat_message_uses_user_provider() -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="chat-cmd-"))
    try:
        paths = resolve_data_paths(temp_dir)
        repository = DataRepository(paths)
        repository.save_users(
            BotUsers(
                users=[
                    BotUser(
                        chat_id=111,
                        language="en",
                        role="ordinary",
                        llm_provider="gpt",
                    )
                ]
            )
        )
        repository.save_config(AppConfig(enable_llm_summaries=True))
        repository.save_portfolio(
            Portfolio(positions=[Position(ticker="AAPL", shares=2)])
        )
        repository.save_state(BotState())
        repository.save_news_cache(NewsCache())

        settings = RuntimeSettings(
            telegram_bot_token="token",
            telegram_chat_id="111",
            ollama_base_url="http://ollama:11434",
            ollama_model="test-model",
            hku_api_key="test-key",
        )
        llm = LlmClient(settings=settings, app_config=AppConfig(enable_llm_summaries=True))
        commands = BotCommands(repository=repository, llm=llm, settings=settings)

        with patch.object(llm, "generate", return_value="AAPL looks stable today.") as generate:
            reply = commands.chat_message(111, "How is my portfolio?")
            if "AAPL looks stable" not in reply:
                raise AssertionError(f"unexpected reply: {reply}")
            if generate.call_args.kwargs.get("provider") != "gpt":
                raise AssertionError("chat should use the user's gpt provider")

        session = repository.get_chat_session(111)
        if len(session.turns) != 2:
            raise AssertionError("expected user+assistant turns to be stored")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_generate_respects_explicit_provider() -> None:
    settings = RuntimeSettings(
        telegram_bot_token="token",
        telegram_chat_id="111",
        ollama_base_url="http://ollama:11434",
        ollama_model="test-model",
        hku_api_key="test-key",
    )
    client = LlmClient(settings=settings)

    with patch.object(client, "_generate_ollama_source", return_value=("ok", "ollama")) as ollama:
        with patch.object(client, "_generate_hku_claude") as claude:
            text = client.generate("hello", provider="ollama")
            if text != "ok":
                raise AssertionError("ollama generate failed")
            ollama.assert_called_once()
            claude.assert_not_called()

    with patch.object(
        client,
        "_generate_hku_claude",
        side_effect=LlmGenerationError("claude down"),
    ):
        try:
            client.generate("hello", provider="claude")
            raise AssertionError("explicit claude failure should raise")
        except LlmGenerationError:
            pass


def run_test() -> None:
    test_normalize_provider()
    test_default_provider_and_set_llm()
    test_chat_prompt_includes_context()
    test_chat_message_uses_user_provider()
    test_generate_respects_explicit_provider()
    print("Portfolio chat checks passed.")


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
