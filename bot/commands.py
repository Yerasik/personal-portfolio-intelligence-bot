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
from analysis.strategy_writer import (
    build_strategy_text_by_language,
    localized_strategy_text,
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
    format_strategy_detail,
    format_strategy_list,
    format_ticker_analysis,
)
from bot.i18n import SUPPORTED_LANGUAGES, normalize_language, t
from bot.notifier import TelegramNotifier
from config.settings import RuntimeSettings
from storage.models import TickerStrategy, UserRole
from storage.portfolio_ops import normalize_ticker
from storage.repository import DataRepository


@dataclass
class BotCommands:
    """Command handlers delegate data loading and analysis here."""

    repository: DataRepository
    llm: LlmClient
    settings: RuntimeSettings

    def _notifier(self) -> TelegramNotifier:
        return TelegramNotifier(self.settings)

    def _lang(self, chat_id: int) -> str:
        return self.repository.user_language(chat_id)

    def _is_developer(self, chat_id: int) -> bool:
        return self.repository.is_developer(chat_id)

    def start_message(self, chat_id: int) -> str:
        """Return the welcome text for /start."""
        return format_start(
            lang=self._lang(chat_id),
            is_developer=self._is_developer(chat_id),
        )

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
        return format_portfolio(
            portfolio,
            state,
            lang=self._lang(chat_id),
            is_developer=self._is_developer(chat_id),
        )

    def industries_message(self, chat_id: int) -> str:
        """Load config + news cache and summarize focus industries."""
        lang = self._lang(chat_id)
        is_developer = self._is_developer(chat_id)
        app_config = self.repository.load_config()
        portfolio = self.repository.load_portfolio()
        ticker_industries = self.repository.load_ticker_industries()
        news_cache = self.repository.load_news_cache()
        focus_industries = build_news_focus_industries(
            app_config.focus_industries,
            portfolio,
            ticker_industries.ticker_to_industry,
        )
        return format_industries(
            focus_industries,
            news_cache,
            lang=lang,
            is_developer=is_developer,
        )

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

        return format_analyze(
            alerts,
            advisory,
            app_config,
            lang=lang,
            is_developer=self._is_developer(chat_id),
        )

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
            is_developer=self._is_developer(chat_id),
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
        if result.success:
            self.repository.remove_ticker_strategy(ticker)
        key = "remove_ticker_ok" if result.success else "remove_ticker_fail"
        return t(key, lang, message=result.message)

    def _strategy_display_text(self, strategy: TickerStrategy, lang: str) -> str:
        """Resolve strategy copy for the user's language, caching on demand."""
        from bot.i18n import normalize_language

        normalized = normalize_language(lang)
        cached = strategy.strategy_text_by_language.get(normalized)
        if cached:
            return cached

        app_config = self.repository.load_config()
        text = localized_strategy_text(
            self.llm,
            strategy,
            normalized,
            enabled=app_config.enable_llm_summaries,
        )
        if normalized not in strategy.strategy_text_by_language:
            self.repository.set_strategy_translation(strategy.ticker, normalized, text)
        return text

    def strategy_message(self, chat_id: int, ticker: str | None = None) -> str:
        """Show stored investment ideas for the portfolio or one ticker."""
        lang = self._lang(chat_id)
        is_developer = self._is_developer(chat_id)
        strategies = self.repository.load_ticker_strategies().by_ticker

        if ticker:
            symbol = normalize_ticker(ticker)
            record = strategies.get(symbol)
            if record is None:
                return t("strategy_not_found", lang, symbol=symbol)
            display_text = self._strategy_display_text(record, lang)
            return format_strategy_detail(
                record,
                display_text=display_text,
                lang=lang,
                is_developer=is_developer,
            )

        portfolio = self.repository.load_portfolio()
        display_by_ticker: dict[str, str] = {}
        for position in portfolio.positions:
            symbol = normalize_ticker(position.ticker)
            record = strategies.get(symbol)
            if record is not None:
                display_by_ticker[symbol] = self._strategy_display_text(record, lang)
        return format_strategy_list(
            portfolio,
            strategies,
            display_by_ticker=display_by_ticker,
            lang=lang,
        )

    def add_ticker_strategy_message(
        self,
        chat_id: int,
        ticker: str,
        shares: float,
        reasoning: str,
    ) -> str:
        """Add a holding, generate strategy copy, and notify ordinary users."""
        lang = self._lang(chat_id)
        app_config = self.repository.load_config()
        result = self.repository.add_ticker_to_portfolio(ticker, shares=shares)
        if not result.success:
            return t("add_ticker_strategy_fail", lang, message=result.message)

        symbol = result.ticker
        state = self.repository.load_state()
        quote = state.latest_prices.get(symbol)
        company_name = quote.company_name if quote is not None else ""

        user_languages = {
            user.language for user in self.repository.load_users().users
        } or {"en"}
        generated, by_language = build_strategy_text_by_language(
            self.llm,
            symbol,
            reasoning,
            shares=shares,
            company_name=company_name,
            languages=user_languages,
            enabled=app_config.enable_llm_summaries,
        )
        self.repository.upsert_ticker_strategy(
            symbol,
            developer_reasoning=reasoning,
            strategy_text=generated.strategy_text,
            shares_at_add=shares,
            strategy_text_by_language=by_language,
        )

        notified = 0
        if result.is_new_position:
            localized_for_notify = by_language.get("en", generated.strategy_text)
            notified = self._notifier().notify_new_ticker_strategy(
                self.repository,
                symbol,
                shares,
                llm=self.llm,
                app_config=app_config,
                strategy_text=localized_for_notify,
                announcement_en=generated.announcement_text,
                state=state,
                strategy_text_by_language=by_language,
            )
            key = (
                "add_ticker_strategy_ok"
                if notified
                else "add_ticker_strategy_ok_no_notify"
            )
            return t(key, lang, symbol=symbol, count=notified)

        return t("add_ticker_strategy_ok_no_notify", lang, symbol=symbol)

    def edit_strategy_message(self, chat_id: int, ticker: str, strategy_text: str) -> str:
        """Hard-overwrite the stored strategy text for a ticker."""
        lang = self._lang(chat_id)
        symbol = normalize_ticker(ticker)
        cleaned = strategy_text.strip()
        if not cleaned:
            return t("edit_strategy_empty", lang)

        ok, result = self.repository.edit_ticker_strategy_text(
            symbol,
            cleaned,
            editor_language=lang,
        )
        if ok:
            return t("edit_strategy_ok", lang, symbol=symbol)
        if result == "not_found":
            return t("edit_strategy_not_found", lang, symbol=symbol)
        return t("edit_strategy_fail", lang, message=result)

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
        from scheduler.jobs import reload_scheduler_jobs

        self.repository.load_config()
        rescheduled = reload_scheduler_jobs()
        lang = self._lang(chat_id)
        if rescheduled:
            return f"{t('reload_ok', lang)}\n{t('reload_jobs_ok', lang)}"
        return t("reload_ok", lang)

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
