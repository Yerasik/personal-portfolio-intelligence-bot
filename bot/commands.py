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
from bot.i18n import SUPPORTED_LANGUAGES, normalize_language, t
from storage.models import UserRole
from storage.repository import DataRepository


@dataclass
class BotCommands:
    """Command handlers delegate data loading and analysis here."""

    repository: DataRepository
    llm: LlmClient

    def _lang(self, chat_id: int) -> str:
        return self.repository.user_language(chat_id)

    def _is_developer(self, chat_id: int) -> bool:
        return self.repository.is_developer(chat_id)

    def start_message(self, chat_id: int) -> str:
        """Return the welcome text for /start."""
        return format_start(lang=self._lang(chat_id))

    def help_message(self, chat_id: int) -> str:
        """Return the command list for /help."""
        return format_help(
            lang=self._lang(chat_id),
            is_developer=self._is_developer(chat_id),
        )

    def portfolio_message(self, chat_id: int) -> str:
        """Load portfolio + state and format holdings with latest prices."""
        portfolio = self.repository.load_portfolio()
        state = self.repository.load_state()
        return format_portfolio(portfolio, state, lang=self._lang(chat_id))

    def industries_message(self, chat_id: int) -> str:
        """Load config + news cache and summarize focus industries."""
        lang = self._lang(chat_id)
        app_config = self.repository.load_config()
        portfolio = self.repository.load_portfolio()
        ticker_industries = self.repository.load_ticker_industries()
        news_cache = self.repository.load_news_cache()
        focus_industries = build_news_focus_industries(
            app_config.focus_industries,
            portfolio,
            ticker_industries.ticker_to_industry,
        )
        return format_industries(focus_industries, news_cache, lang=lang)

    def analyze_message(self, chat_id: int) -> str:
        """Run rules (and optional LLM) and format an on-demand advisory."""
        lang = self._lang(chat_id)
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
                language=lang,
            )

        return format_analyze(alerts, advisory, app_config, lang=lang)

    def news_summary_message(self, chat_id: int) -> str:
        """Summarize cached news by sector and portfolio ticker via the LLM."""
        lang = self._lang(chat_id)
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
            language=lang,
        )
        return format_news_summary(summary, lang=lang)

    def analyze_ticker_message(
        self,
        chat_id: int,
        ticker: str,
        *,
        window: str = "today",
    ) -> str:
        """Explain the latest price move for one ticker using the shared helper."""
        lang = self._lang(chat_id)
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
                language=lang,
            )

        return format_ticker_analysis(
            symbol,
            quote,
            window,
            explanation,
            app_config,
            lang=lang,
        )

    def add_ticker_message(self, chat_id: int, ticker: str, shares: float = 1.0) -> str:
        """Validate and add a ticker to portfolio.json."""
        lang = self._lang(chat_id)
        result = self.repository.add_ticker_to_portfolio(ticker, shares=shares)
        key = "add_ticker_ok" if result.success else "add_ticker_fail"
        return t(key, lang, message=result.message)

    def remove_ticker_message(self, chat_id: int, ticker: str) -> str:
        """Remove a ticker from portfolio.json."""
        lang = self._lang(chat_id)
        result = self.repository.remove_ticker_from_portfolio(ticker)
        key = "remove_ticker_ok" if result.success else "remove_ticker_fail"
        return t(key, lang, message=result.message)

    def current_language_message(self, chat_id: int) -> str:
        """Show the user's stored language and usage hint."""
        lang = self._lang(chat_id)
        return f"{t('language_current', lang, language=lang)}\n\n{t('language_usage', lang)}"

    def set_language_message(self, chat_id: int, language: str) -> str:
        """Update the requesting user's language preference."""
        lang = self._lang(chat_id)
        normalized = normalize_language(language)
        if normalized not in SUPPORTED_LANGUAGES:
            return t("language_invalid", lang)
        ok, result = self.repository.set_user_language(chat_id, normalized)
        if not ok:
            return t("language_invalid", lang)
        return t("language_set", normalized, language=normalized)

    def reload_config_message(self, chat_id: int) -> str:
        """Reload config.json from disk (developer diagnostics)."""
        self.repository.load_config()
        return t("reload_ok", self._lang(chat_id))

    def debug_state_message(self, chat_id: int) -> str:
        """Return internal counters for developer diagnostics."""
        lang = self._lang(chat_id)
        portfolio = self.repository.load_portfolio()
        state = self.repository.load_state()
        news_cache = self.repository.load_news_cache()
        users = self.repository.load_users()
        return t(
            "debug_state",
            lang,
            positions=len(portfolio.positions),
            news=len(news_cache.items),
            pending=len(state.pending_alerts),
            users=len(users.users),
        )

    def list_users_message(self, chat_id: int) -> str:
        """List authorized users (developer only)."""
        lang = self._lang(chat_id)
        users = self.repository.load_users()
        if not users.users:
            return t("users_list", lang, lines="(none)")
        lines = [
            f"- {user.chat_id}: role={user.role}, lang={user.language}"
            for user in users.users
        ]
        return t("users_list", lang, lines="\n".join(lines))

    def add_user_message(
        self,
        chat_id: int,
        target_chat_id: int,
        *,
        role: UserRole = "ordinary",
        language: str = "en",
    ) -> str:
        """Authorize a new Telegram user (developer only)."""
        lang = self._lang(chat_id)
        ok, result = self.repository.add_user(
            target_chat_id,
            role=role,
            language=language,
        )
        if ok:
            user = self.repository.find_user(target_chat_id)
            assert user is not None
            return t(
                "add_user_ok",
                lang,
                chat_id=target_chat_id,
                role=user.role,
                language=user.language,
            )
        if result == "exists":
            return t("user_exists", lang, chat_id=target_chat_id)
        return t("language_invalid", lang)

    def remove_user_message(self, chat_id: int, target_chat_id: int) -> str:
        """Revoke access for a Telegram user (developer only)."""
        lang = self._lang(chat_id)
        if target_chat_id == chat_id:
            return t("cannot_remove_self", lang)
        ok, result = self.repository.remove_user(target_chat_id)
        if ok:
            return t("remove_user_ok", lang, chat_id=target_chat_id)
        return t("user_not_found", lang, chat_id=target_chat_id)
