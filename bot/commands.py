"""Telegram command business logic.

Handlers stay thin; this module loads JSON data, runs analysis, and returns
formatted plain-text strings ready for Telegram.
"""

from __future__ import annotations

from dataclasses import dataclass

from analysis.llm import LlmAdvisoryResult, LlmClient
from analysis.rules import RulesEngine
from bot.formatter import (
    format_analyze,
    format_help,
    format_industries,
    format_portfolio,
    format_start,
)
from storage.repository import DataRepository


@dataclass
class BotCommands:
    """Command handlers delegate data loading and analysis here."""

    repository: DataRepository
    llm: LlmClient

    def start_message(self) -> str:
        """Return the welcome text for /start."""
        return format_start()

    def help_message(self) -> str:
        """Return the command list for /help."""
        return format_help()

    def portfolio_message(self) -> str:
        """Load portfolio + state and format holdings with latest prices."""
        portfolio = self.repository.load_portfolio()
        state = self.repository.load_state()
        return format_portfolio(portfolio, state)

    def industries_message(self) -> str:
        """Load config + news cache and summarize focus industries."""
        app_config = self.repository.load_config()
        news_cache = self.repository.load_news_cache()
        return format_industries(app_config, news_cache)

    def analyze_message(self) -> str:
        """Run rules (and optional LLM) and format an on-demand advisory."""
        app_config = self.repository.load_config()
        portfolio = self.repository.load_portfolio()
        state = self.repository.load_state()
        news_cache = self.repository.load_news_cache()

        rules = RulesEngine(app_config=app_config)
        alerts = rules.evaluate(portfolio, state, news_cache)

        advisory: LlmAdvisoryResult | None = None
        if app_config.enable_llm_summaries:
            advisory = self.llm.synthesize_advisory(
                portfolio,
                app_config,
                state,
                news_cache,
                alerts,
            )

        return format_analyze(alerts, advisory, app_config)
