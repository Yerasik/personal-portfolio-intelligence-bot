"""Telegram command business logic.

Handlers stay thin; this module loads JSON data, runs analysis, and returns
formatted plain-text strings ready for Telegram.
"""

from __future__ import annotations

from dataclasses import dataclass

from analysis.industries import build_news_focus_industries
from analysis.llm import LlmAdvisoryResult, LlmClient
from analysis.move_explainer import (
    PriceMoveExplanation,
    explain_price_move,
    recent_news_titles_for_ticker,
)
from analysis.news_summarizer import summarize_news
from analysis.rules import RulesEngine
from bot.formatter import (
    format_analyze,
    format_help,
    format_industries,
    format_news_summary,
    format_portfolio,
    format_start,
    format_ticker_analysis,
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
        portfolio = self.repository.load_portfolio()
        ticker_industries = self.repository.load_ticker_industries()
        news_cache = self.repository.load_news_cache()
        focus_industries = build_news_focus_industries(
            app_config.focus_industries,
            portfolio,
            ticker_industries.ticker_to_industry,
        )
        return format_industries(focus_industries, news_cache)

    def analyze_message(self) -> str:
        """Run rules (and optional LLM) and format an on-demand advisory."""
        app_config = self.repository.load_config()
        portfolio = self.repository.load_portfolio()
        ticker_industries = self.repository.load_ticker_industries()
        state = self.repository.load_state()
        news_cache = self.repository.load_news_cache()

        rules = RulesEngine(
            app_config=app_config,
            ticker_to_industry=ticker_industries.ticker_to_industry,
        )
        alerts = rules.evaluate(portfolio, state, news_cache)

        advisory: LlmAdvisoryResult | None = None
        if app_config.enable_llm_summaries:
            advisory = self.llm.synthesize_advisory(
                portfolio,
                app_config,
                state,
                news_cache,
                alerts,
                ticker_to_industry=ticker_industries.ticker_to_industry,
            )

        return format_analyze(alerts, advisory, app_config)

    def news_summary_message(self) -> str:
        """Summarize cached news by sector and portfolio ticker via the LLM."""
        app_config = self.repository.load_config()
        portfolio = self.repository.load_portfolio()
        ticker_industries = self.repository.load_ticker_industries()
        state = self.repository.load_state()
        news_cache = self.repository.load_news_cache()

        company_names = {
            symbol: quote.company_name
            for symbol, quote in state.latest_prices.items()
            if quote.company_name
        }
        summary = summarize_news(
            self.llm,
            portfolio,
            app_config,
            news_cache,
            ticker_industries.ticker_to_industry,
            company_names=company_names,
            enabled=app_config.enable_llm_summaries,
        )
        return format_news_summary(summary)

    def analyze_ticker_message(self, ticker: str, *, window: str = "today") -> str:
        """Explain the latest price move for one ticker using the shared helper."""
        symbol = ticker.strip().upper()
        app_config = self.repository.load_config()
        state = self.repository.load_state()
        news_cache = self.repository.load_news_cache()

        quote = state.latest_prices.get(symbol)

        explanation: PriceMoveExplanation | None = None
        if (
            app_config.enable_llm_summaries
            and quote is not None
            and quote.change_pct is not None
        ):
            news = recent_news_titles_for_ticker(news_cache, symbol)
            explanation = explain_price_move(
                self.llm,
                symbol,
                quote.change_pct,
                window,
                news,
                company_name=quote.company_name,
                sector=quote.sector,
            )

        return format_ticker_analysis(symbol, quote, window, explanation, app_config)
