#!/usr/bin/env python3
"""Smoke test for Telegram command formatting and logic."""

from __future__ import annotations

import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.llm import LlmClient
from bot.commands import BotCommands
from bot.formatter import format_help, format_portfolio, format_start
from bot.handlers import is_authorized
from config.settings import RuntimeSettings
from storage.models import AppConfig, BotState, MarketQuote, NewsCache, NewsItem, Portfolio, Position
from storage.paths import resolve_data_paths
from storage.repository import DataRepository

NOW = datetime(2026, 6, 4, 12, 0, tzinfo=UTC)


class FakeUpdate:
    def __init__(self, chat_id: int) -> None:
        self.effective_chat = type("Chat", (), {"id": chat_id})()


def run_test() -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="bot-test-"))
    print(f"Using temp data dir: {temp_dir}")

    try:
        paths = resolve_data_paths(temp_dir)
        repository = DataRepository(paths)
        repository.save_config(AppConfig(focus_industries=["Consumer Electronics"]))
        repository.save_portfolio(
            Portfolio(positions=[Position(ticker="AAPL", shares=10, cost_basis=150.0)])
        )
        state = BotState(
            latest_prices={
                "AAPL": MarketQuote(
                    ticker="AAPL",
                    price=180.0,
                    change_pct=-2.5,
                    volume=1000,
                    company_name="Apple Inc.",
                    fetched_at=NOW,
                )
            },
            last_market_fetch_at=NOW,
        )
        repository.save_state(state)
        repository.save_news_cache(
            NewsCache(
                items=[
                    NewsItem(
                        id="n1",
                        title="Apple update",
                        source="Test",
                        url="https://example.com/n1",
                        published_at=NOW,
                        fetched_at=NOW,
                        sector_tags=["Consumer Electronics"],
                    )
                ],
                updated_at=NOW,
            )
        )

        settings = RuntimeSettings(
            telegram_bot_token="test-token",
            telegram_chat_id="12345",
        )
        llm = LlmClient(settings=settings)
        commands = BotCommands(repository=repository, llm=llm)

        portfolio_text = commands.portfolio_message()
        if "AAPL" not in portfolio_text or "180.00" not in portfolio_text:
            raise AssertionError("portfolio message missing expected content")

        industries_text = commands.industries_message()
        if "Consumer Electronics" not in industries_text or "1 cached" not in industries_text:
            raise AssertionError("industries message missing expected content")

        analyze_text = commands.analyze_message()
        if "Portfolio analysis" not in analyze_text:
            raise AssertionError("analyze message missing header")

        class SettingsStub:
            telegram_chat_id = "12345"

        if not is_authorized(FakeUpdate(12345), SettingsStub()):  # type: ignore[arg-type]
            raise AssertionError("authorized chat should pass")
        if is_authorized(FakeUpdate(99999), SettingsStub()):  # type: ignore[arg-type]
            raise AssertionError("unauthorized chat should fail")

        print(format_start())
        print(format_help())
        print("Portfolio preview:\n", portfolio_text)
        print("Industries preview:\n", industries_text)
        print("Analyze preview:\n", analyze_text)
        print("Telegram bot command checks passed.")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
