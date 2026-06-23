"""Telegram command business logic.

Handlers stay thin; this module loads JSON data, runs analysis, and returns
formatted plain-text strings ready for Telegram.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from analysis.industries import build_news_fetch_industries, build_news_focus_industries
from analysis.llm import LlmAdvisoryResult, LlmClient
from analysis.move_explainer import (
    PriceMoveExplanation,
    explain_price_move,
    recent_news_titles_for_ticker,
)
from analysis.strategy_writer import (
    build_strategy_text_by_language,
    generate_sell_announcement_from_reasoning,
    localized_strategy_text,
)
from analysis.news_summarizer import iter_news_summary_groups
from analysis.portfolio_risk import estimate_portfolio_risk
from analysis.rules import RulesEngine
from bot.formatter import (
    format_analyze,
    format_help,
    format_industries,
    format_news_summary,
    format_news_summary_messages,
    format_portfolio,
    format_pros_cons_analysis,
    format_start,
    format_strategy_detail,
    format_strategy_list,
    format_ticker_analysis,
    iter_format_news_summary_messages,
    truncate_message,
)
from bot.i18n import SUPPORTED_LANGUAGES, normalize_language, t
from bot.notifier import TelegramNotifier
from config.settings import RuntimeSettings
from storage.models import TickerStrategy, UserRole
from storage.portfolio_ops import PortfolioTickerResult, normalize_ticker, portfolio_has_ticker
from storage.repository import DataRepository

logger = logging.getLogger(__name__)


@dataclass
class BotCommands:
    """Command handlers delegate data loading and analysis here."""

    repository: DataRepository
    llm: LlmClient
    settings: RuntimeSettings

    def _notifier(self) -> TelegramNotifier:
        return TelegramNotifier(self.settings)

    def _deliver_alerts_after_portfolio_change(self) -> None:
        """Refresh quotes and push any new warning/urgent alerts to all users."""
        from scheduler.alert_delivery import refresh_market_data_and_deliver_alerts

        try:
            refresh_market_data_and_deliver_alerts(
                self.repository,
                self.settings,
                self._notifier(),
                llm=self.llm,
            )
        except Exception:
            logger.exception("Immediate alert delivery after portfolio change failed")

    def _holding_shares(self, symbol: str) -> float:
        portfolio = self.repository.load_portfolio()
        normalized = normalize_ticker(symbol)
        for position in portfolio.positions:
            if normalize_ticker(position.ticker) == normalized:
                return position.shares
        return 0.0

    def _notify_ordinary_portfolio_add(
        self,
        result: PortfolioTickerResult,
        *,
        shares_added: float,
    ) -> int:
        change = "added_new" if result.is_new_position else "added_shares"
        share_amount = (
            self._holding_shares(result.ticker)
            if result.is_new_position
            else shares_added
        )
        return self._notifier().notify_portfolio_change(
            self.repository,
            change=change,
            symbol=result.ticker,
            shares=share_amount,
        )

    def _notify_ordinary_portfolio_remove(self, symbol: str) -> int:
        return self._notifier().notify_portfolio_change(
            self.repository,
            change="removed",
            symbol=symbol,
        )

    def _strategy_text_for_delivery(self, strategy: TickerStrategy, lang: str) -> str:
        """Resolve strategy copy for outbound notifications without persisting translations."""
        from bot.i18n import normalize_language

        normalized = normalize_language(lang)
        cached = strategy.strategy_text_by_language.get(normalized)
        if cached:
            return cached
        if normalized == "en":
            return strategy.strategy_text
        app_config = self.repository.load_config()
        return localized_strategy_text(
            self.llm,
            strategy,
            normalized,
            enabled=app_config.enable_llm_summaries,
        )

    def _notify_ordinary_strategy_update(self, symbol: str) -> int:
        strategy = self.repository.get_ticker_strategy(symbol)
        if strategy is None:
            return 0

        return self._notifier().notify_strategy_content(
            self.repository,
            symbol=symbol,
            text_for_language=lambda lang, record=strategy: self._strategy_text_for_delivery(
                record,
                lang,
            ),
        )

    def _notify_ordinary_strategy_announcement(
        self,
        symbol: str,
        shares: float,
        *,
        announcement_en: str,
        strategy_text_by_language: dict[str, str],
        strategy_text: str,
    ) -> int:
        state = self.repository.load_state()
        app_config = self.repository.load_config()
        return self._notifier().notify_new_ticker_strategy(
            self.repository,
            symbol,
            shares,
            llm=self.llm,
            app_config=app_config,
            strategy_text=strategy_text,
            announcement_en=announcement_en,
            state=state,
            strategy_text_by_language=strategy_text_by_language,
        )

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
        signals = self.repository.load_signals()

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

        risk = estimate_portfolio_risk(
            portfolio,
            state,
            signals,
            alerts,
            app_config,
        )

        return format_analyze(
            alerts,
            advisory,
            app_config,
            portfolio=portfolio,
            sentiment_by_ticker=signals.sentiment,
            news_cache=news_cache,
            ticker_to_industry=ticker_industries.ticker_to_industry,
            risk=risk,
            lang=lang,
            is_developer=self._is_developer(chat_id),
        )

    def analyze_pros_message(self, chat_id: int, ticker: str | None = None) -> str:
        """Show or generate pros/cons memos from signals.json."""
        lang = self._lang(chat_id)
        app_config = self.repository.load_config()
        portfolio = self.repository.load_portfolio()

        if ticker:
            symbol = normalize_ticker(ticker)
            engine = ProsConsEngine(self.llm, app_config)
            result = engine.generate_for_ticker(symbol, repository=self.repository)
            return format_pros_cons_analysis(
                {symbol: result.memo},
                generated_for={symbol},
                lang=lang,
            )

        signals = self.repository.load_signals()
        memos = {
            normalize_ticker(position.ticker): record.memo
            for position in portfolio.positions
            if (record := signals.pros_cons.get(normalize_ticker(position.ticker)))
            is not None
        }
        if not memos:
            return t("analyze_pros_empty", lang)
        return format_pros_cons_analysis(memos, lang=lang)

    def refresh_news_cache_for_summary(self) -> int:
        """Fetch latest RSS news (including macro) before /news_summary."""
        from collectors.news_data import NewsDataService

        app_config = self.repository.load_config()
        portfolio = self.repository.load_portfolio()
        ticker_industries = self.repository.load_ticker_industries()
        focus_industries = build_news_fetch_industries(
            app_config.focus_industries,
            portfolio,
            ticker_industries.ticker_to_industry,
            app_config.macro_sector_label,
        )
        batch = NewsDataService().run(
            self.repository,
            app_config,
            portfolio,
            focus_industries=focus_industries,
        )
        logger.info(
            "News refresh for /news_summary: %d new article(s)",
            batch.new_count,
        )
        return batch.new_count

    def iter_news_summary_messages(self, chat_id: int):
        """Stream cached news summaries one Telegram message at a time."""
        self.refresh_news_cache_for_summary()
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
        groups = iter_news_summary_groups(
            self.llm,
            portfolio,
            app_config,
            news_cache,
            ticker_industries.ticker_to_industry,
            company_names=company_names,
            enabled=app_config.enable_llm_summaries,
            language=lang,
        )
        return iter_format_news_summary_messages(groups, lang=lang)

    def news_summary_messages(self, chat_id: int) -> list[str]:
        """Summarize cached news by sector and portfolio ticker via the LLM."""
        messages = list(self.iter_news_summary_messages(chat_id))
        if not messages:
            return messages
        footer = t("news_footer", self._lang(chat_id))
        messages[-1] = truncate_message(f"{messages[-1]}\n\n{footer}")
        return messages

    def news_summary_message(self, chat_id: int) -> str:
        """Legacy single-string news summary (joined messages)."""
        return "\n\n".join(self.news_summary_messages(chat_id))

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
        portfolio = self.repository.load_portfolio()
        state = self.repository.load_state()
        news_cache = self.repository.load_news_cache()

        quote = state.latest_prices.get(symbol)
        position_value = valuation_for_ticker(portfolio, state, symbol)

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
            position_valuation=position_value,
            lang=lang,
            is_developer=self._is_developer(chat_id),
        )

    def add_ticker_message(self, chat_id: int, ticker: str, shares: float = 1.0) -> str:
        """Validate and add a ticker to portfolio.json."""
        lang = self._lang(chat_id)
        result = self.repository.add_ticker_to_portfolio(ticker, shares=shares)
        if result.success:
            notified = self._notify_ordinary_portfolio_add(
                result,
                shares_added=shares,
            )
            self._deliver_alerts_after_portfolio_change()
            message = t("add_ticker_ok", lang, message=result.message)
            if notified:
                message = f"{message}\n{t('users_notified', lang, count=notified)}"
            return message
        return t("add_ticker_fail", lang, message=result.message)

    def remove_ticker_message(self, chat_id: int, ticker: str) -> str:
        """Remove a ticker from portfolio.json."""
        lang = self._lang(chat_id)
        symbol = normalize_ticker(ticker)
        result = self.repository.remove_ticker_from_portfolio(ticker)
        if result.success:
            self.repository.remove_ticker_strategy(ticker)
            notified = self._notify_ordinary_portfolio_remove(symbol)
            self._deliver_alerts_after_portfolio_change()
            message = t("remove_ticker_ok", lang, message=result.message)
            if notified:
                message = f"{message}\n{t('users_notified', lang, count=notified)}"
            return message
        return t("remove_ticker_fail", lang, message=result.message)

    def sell_ticker_message(
        self,
        chat_id: int,
        ticker: str,
        sell_price: float,
        reasoning: str,
        *,
        shares: float | None = None,
    ) -> str:
        """Sell shares at a price, credit cash, and notify ordinary users."""
        lang = self._lang(chat_id)
        app_config = self.repository.load_config()
        symbol = normalize_ticker(ticker)
        result = self.repository.sell_ticker_from_portfolio(
            ticker,
            sell_price=sell_price,
            shares=shares,
        )
        if not result.success:
            return t("sell_ticker_fail", lang, message=result.message)

        if result.fully_sold:
            self.repository.remove_ticker_strategy(symbol)

        state = self.repository.load_state()
        quote = state.latest_prices.get(symbol)
        company_name = quote.company_name if quote is not None else ""
        announcement_en = generate_sell_announcement_from_reasoning(
            self.llm,
            symbol,
            reasoning,
            shares_sold=result.shares_sold,
            sell_price=result.sell_price,
            company_name=company_name,
            language="en",
            enabled=app_config.enable_llm_summaries,
        )
        notified = self._notifier().notify_ticker_sold(
            self.repository,
            symbol,
            shares_sold=result.shares_sold,
            sell_price=result.sell_price,
            fully_sold=result.fully_sold,
            llm=self.llm,
            app_config=app_config,
            announcement_en=announcement_en,
            state=state,
        )
        self._deliver_alerts_after_portfolio_change()

        message = t(
            "sell_ticker_ok",
            lang,
            message=result.message,
            cash=result.cash_balance,
        )
        if notified:
            message = f"{message}\n{t('users_notified', lang, count=notified)}"
        return message

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
        shares: float | None,
        reasoning: str,
    ) -> str:
        """Add a holding or save strategy for an existing one, then notify users."""
        lang = self._lang(chat_id)
        app_config = self.repository.load_config()
        portfolio = self.repository.load_portfolio()
        symbol = normalize_ticker(ticker)
        is_new_position = not portfolio_has_ticker(portfolio, symbol)

        if is_new_position:
            add_shares = shares if shares is not None else 1.0
            result = self.repository.add_ticker_to_portfolio(ticker, shares=add_shares)
            if not result.success:
                return t("add_ticker_strategy_fail", lang, message=result.message)
            position_shares = add_shares
        else:
            position = next(
                (
                    item
                    for item in portfolio.positions
                    if normalize_ticker(item.ticker) == symbol
                ),
                None,
            )
            if position is None:
                return t(
                    "add_ticker_strategy_fail",
                    lang,
                    message=f"{symbol} is not in the portfolio.",
                )
            result = PortfolioTickerResult(
                True,
                f"Saved strategy for {symbol}.",
                symbol,
                is_new_position=False,
            )
            position_shares = position.shares

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
            shares=position_shares,
            company_name=company_name,
            languages=user_languages,
            enabled=app_config.enable_llm_summaries,
        )
        existing_strategy = self.repository.get_ticker_strategy(symbol)
        shares_at_add = (
            (shares if shares is not None else 1.0)
            if is_new_position
            else (
                existing_strategy.shares_at_add
                if existing_strategy is not None and existing_strategy.shares_at_add is not None
                else position_shares
            )
        )
        self.repository.upsert_ticker_strategy(
            symbol,
            developer_reasoning=reasoning,
            strategy_text=generated.strategy_text,
            shares_at_add=shares_at_add,
            strategy_text_by_language=by_language,
        )

        notified = 0
        if is_new_position:
            localized_for_notify = by_language.get("en", generated.strategy_text)
            notified = self._notify_ordinary_strategy_announcement(
                symbol,
                position_shares,
                announcement_en=generated.announcement_text,
                strategy_text_by_language=by_language,
                strategy_text=localized_for_notify,
            )
            key = (
                "add_ticker_strategy_ok"
                if notified
                else "add_ticker_strategy_ok_no_notify"
            )
            self._deliver_alerts_after_portfolio_change()
            return t(key, lang, symbol=symbol, count=notified)

        notified += self._notifier().notify_strategy_content(
            self.repository,
            symbol=symbol,
            text_for_language=lambda language, bl=by_language, fallback=generated.strategy_text: (
                bl.get(language) or bl.get("en", fallback)
            ),
        )
        self._deliver_alerts_after_portfolio_change()
        if notified:
            return t("add_ticker_strategy_ok", lang, symbol=symbol, count=notified)
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
            notified = self._notify_ordinary_strategy_update(symbol)
            self._deliver_alerts_after_portfolio_change()
            message = t("edit_strategy_ok", lang, symbol=symbol)
            if notified:
                message = f"{message}\n{t('users_notified', lang, count=notified)}"
            return message
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
