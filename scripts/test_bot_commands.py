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
from bot.formatter import format_alert, format_help, format_portfolio, format_start
from bot.handlers import is_authorized
from bot.menu import main_menu_keyboard
from config.settings import RuntimeSettings
from storage.models import (
    AppConfig,
    BotState,
    BotUser,
    BotUsers,
    MarketQuote,
    NewsCache,
    NewsItem,
    PendingAlert,
    Portfolio,
    Position,
    TickerIndustryMap,
)
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
        repository.save_users(
            BotUsers(
                users=[
                    BotUser(chat_id=12345, language="en", role="developer"),
                    BotUser(chat_id=67890, language="en", role="ordinary"),
                ]
            )
        )
        repository.save_config(AppConfig(focus_industries=["AI"]))
        repository.save_ticker_industries(
            TickerIndustryMap(ticker_to_industry={"AAPL": "Consumer Electronics"})
        )
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

        portfolio_text = commands.portfolio_message(12345)
        if "AAPL" not in portfolio_text or "180.00" not in portfolio_text:
            raise AssertionError("portfolio message missing expected content")

        industries_text = commands.industries_message(12345)
        if "Consumer Electronics" not in industries_text or "1 cached" not in industries_text:
            raise AssertionError("developer industries message missing expected content")

        ordinary_industries = commands.industries_message(67890)
        if "Consumer Electronics" not in ordinary_industries or "1 headline" not in ordinary_industries:
            raise AssertionError("ordinary industries message missing expected content")
        if any(token in ordinary_industries.lower() for token in ("cached", "cache")):
            raise AssertionError("ordinary industries must not mention cache")
        if "+00:00" in ordinary_industries or "T12:00:00" in ordinary_industries:
            raise AssertionError("ordinary industries must not show ISO timestamps")

        ordinary_portfolio = commands.portfolio_message(67890)
        if "+00:00" in ordinary_portfolio or "T12:00:00" in ordinary_portfolio:
            raise AssertionError("ordinary portfolio must not show ISO timestamps")
        if "2026-06-04" not in ordinary_portfolio:
            raise AssertionError("ordinary portfolio should show plain dates")

        sector_alert_text = format_alert(
            PendingAlert(
                id="sector-1",
                type="sector_attention",
                severity="urgent",
                message=(
                    "Sector attention: Consumer Electronics: "
                    "4 articles tagged to Consumer Electronics were found."
                ),
                created_at=NOW,
                industry="Consumer Electronics",
            ),
            lang="en",
        )
        if "Investigate Consumer Electronics" not in sector_alert_text:
            raise AssertionError(
                f"sector alert formatted incorrectly: {sector_alert_text}"
            )

        analyze_text = commands.analyze_message(12345)
        if "Portfolio analysis" not in analyze_text:
            raise AssertionError("analyze message missing header")

        lang_msg = commands.set_language_message(12345, "ru")
        if "Язык изменён" not in lang_msg:
            raise AssertionError(f"set_language failed: {lang_msg}")

        ru_help = commands.help_message(12345)
        if "Справка по командам" not in ru_help:
            raise AssertionError("Russian help header missing after set_language")

        if not is_authorized(FakeUpdate(12345), repository):
            raise AssertionError("authorized chat should pass")
        if is_authorized(FakeUpdate(99999), repository):
            raise AssertionError("unauthorized chat should fail")

        help_dev = commands.help_message(12345)
        if "/reload_config" not in help_dev:
            raise AssertionError("developer help should list reload_config")

        dev_kb = main_menu_keyboard(is_developer=True)
        dev_labels = {
            button.text
            for row in dev_kb.keyboard
            for button in row
        }
        for cmd in ("/list_users", "/add_user", "/remove_user", "/add_ticker", "/remove_ticker"):
            if cmd not in dev_labels:
                raise AssertionError(f"developer keyboard missing {cmd}")

        ordinary_kb = main_menu_keyboard(is_developer=False)
        ordinary_labels = {
            button.text
            for row in ordinary_kb.keyboard
            for button in row
        }
        for cmd in ("/add_user", "/add_ticker", "/remove_ticker"):
            if cmd in ordinary_labels:
                raise AssertionError(f"ordinary keyboard must not expose {cmd}")

        ordinary_help = format_help(lang="en", is_developer=False)
        if any(token in ordinary_help for token in ("/list_users", "/reload_config", "/add_ticker", "/remove_ticker", "Developer")):
            raise AssertionError("ordinary help must not expose developer or portfolio-edit commands")

        print(format_start(lang="en", is_developer=False))
        print(format_help(lang="en", is_developer=True))
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
