"""Telegram command business logic.

Handlers stay thin; this module loads JSON data, runs analysis, and returns
formatted plain-text strings ready for Telegram.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from analysis.cash_balances import format_cash_balance_text
from analysis.industries import build_news_fetch_industries, build_news_focus_industries
from analysis.llm import LlmAdvisoryResult, LlmClient
from collectors.market_data import ensure_cached_quote
from analysis.move_explainer import (
    AnalyzeTickerContext,
    PriceMoveExplanation,
    build_analyze_ticker_prompt,
    explain_price_move,
    explain_ticker_for_analyze,
    fetch_fifty_two_week_range,
    recent_news_titles_for_ticker,
)
from analysis.technical_snapshot import build_technical_snapshot
from analysis.strategy_writer import (
    build_strategy_text_by_language,
    generate_sell_announcement_from_reasoning,
    localized_strategy_text,
)
from analysis.news_summarizer import iter_news_summary_groups
from analysis.performance_chart import render_performance_chart_png
from analysis.ticker_chart import ChartPeriod as TickerChartPeriod, render_ticker_chart_png
from analysis.performance_series import ChartPeriod
from analysis.performance_metrics import compute_performance_metrics
from analysis.portfolio_risk import estimate_portfolio_risk
from analysis.portfolio_valuation import build_portfolio_valuation, valuation_for_ticker
from analysis.risk_metrics import compute_risk_metrics_report
from analysis.scenario_stress import effective_stress_scenarios, run_stress_report
from analysis.technical_snapshot import build_technical_snapshot
from analysis.rules import RulesEngine
from bot.formatter import (
    format_analyze,
    format_catalyst_calendar,
    format_change_briefing,
    format_help,
    format_industries,
    format_news_summary,
    format_news_summary_messages,
    format_performance,
    format_portfolio,
    format_pros_cons_analysis,
    format_risk_metrics,
    format_stress_report,
    format_start,
    format_strategy_detail,
    format_strategy_list,
    format_technical_snapshot,
    format_ticker_analysis,
    iter_format_news_summary_messages,
    truncate_message,
)
from bot.developer_portfolio import (
    DeveloperActionReply,
    clear_developer_action,
    confirm_keyboard,
    load_action,
    mark_action_completed,
    save_pending_action,
    snapshot_strategies,
    undo_keyboard,
)
from bot.sell_args import SellParseResult, parse_sell_args
from bot.i18n import SUPPORTED_LANGUAGES, normalize_language, t
from bot.notifier import TelegramNotifier
from config.settings import RuntimeSettings
from storage.models import DeveloperPortfolioAction, Portfolio, TickerStrategy, UserRole
from storage.portfolio_ops import (
    PortfolioTickerResult,
    normalize_ticker,
    portfolio_has_ticker,
    validate_ticker_format,
)
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
        strategies = self.repository.load_ticker_strategies().by_ticker
        app_config = self.repository.load_config()
        return format_portfolio(
            portfolio,
            state,
            strategies=strategies,
            lang=self._lang(chat_id),
            is_developer=self._is_developer(chat_id),
            detailed_cash_display=app_config.enable_detailed_cash_display,
        )

    def performance_message(self, chat_id: int) -> str:
        """Format return windows and max drawdown from stored snapshots."""
        lang = self._lang(chat_id)
        history = self.repository.load_performance_history()
        metrics = compute_performance_metrics(history)
        if metrics is None:
            return t("performance_empty", lang)
        return format_performance(metrics, lang=lang)

    def performance_chart_png(self, period: ChartPeriod | None = None) -> bytes | None:
        """Render aggregated portfolio value chart for the requested period."""
        history = self.repository.load_performance_history()
        app_config = self.repository.load_config()
        resolved: ChartPeriod = period or app_config.performance_chart_period
        return render_performance_chart_png(
            history,
            period=resolved,
            timezone=app_config.timezone,
        )

    def risk_metrics_message(self, chat_id: int) -> str:
        """Fetch 90-day history and format Sharpe, drawdown, and benchmark alpha."""
        lang = self._lang(chat_id)
        portfolio = self.repository.load_portfolio()
        if not portfolio.positions:
            return t("risk_metrics_empty", lang)

        app_config = self.repository.load_config()
        state = self.repository.load_state()
        valuation = build_portfolio_valuation(portfolio, state)
        weights = {
            item.ticker: item.weight_pct or 0.0 for item in valuation.positions
        }
        if not any(weight > 0 for weight in weights.values()):
            weights = {position.ticker: 1.0 for position in portfolio.positions}

        report = compute_risk_metrics_report(
            weights,
            benchmark_ticker=app_config.benchmark_ticker,
        )
        if report is None:
            return t("risk_metrics_unavailable", lang)
        return format_risk_metrics(report, lang=lang)

    def stress_message(self, chat_id: int, scenario_id: str | None = None) -> str:
        """Run configured stress scenarios and format portfolio impact."""
        lang = self._lang(chat_id)
        portfolio = self.repository.load_portfolio()
        if not portfolio.positions:
            return t("stress_empty", lang)

        app_config = self.repository.load_config()
        scenarios = effective_stress_scenarios(app_config)
        if scenario_id:
            needle = scenario_id.strip().lower()
            scenarios = [item for item in scenarios if item.scenario_id.lower() == needle]
            if not scenarios:
                return t("stress_not_found", lang, scenario_id=scenario_id)

        state = self.repository.load_state()
        ticker_map = self.repository.load_ticker_industries().ticker_to_industry
        report = run_stress_report(
            portfolio,
            state,
            scenarios,
            ticker_to_industry=ticker_map,
        )
        if report is None:
            return t("stress_empty", lang)
        return format_stress_report(report, lang=lang)

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

    def refresh_catalyst_calendar(self) -> str:
        """Fetch earnings and merge manual catalyst events into catalyst_events.json."""
        from collectors.base import CollectorContext
        from collectors.catalyst_calendar import CatalystCalendarCollector

        app_config = self.repository.load_config()
        portfolio = self.repository.load_portfolio()
        context = CollectorContext(
            repository=self.repository,
            app_config=app_config,
            portfolio=portfolio,
        )
        result = CatalystCalendarCollector().run(context)
        if not result.success:
            return result.message
        return result.message

    def calendar_message(self, chat_id: int) -> str:
        """Show upcoming earnings, macro, and policy catalysts."""
        from analysis.catalyst_reminders import upcoming_events

        lang = self._lang(chat_id)
        app_config = self.repository.load_config()
        events_file = self.repository.load_catalyst_events()
        events = upcoming_events(
            events_file,
            days_ahead=min(30, app_config.catalyst_calendar_days_ahead),
        )
        return format_catalyst_calendar(
            events,
            lang=lang,
            timezone_label=app_config.timezone,
        )

    def changes_message(self, chat_id: int, *, force: bool = False) -> str:
        """Build the what-changed-since-yesterday briefing on demand."""
        from analysis.change_briefing import assemble_change_briefing

        lang = self._lang(chat_id)
        app_config = self.repository.load_config()
        if not force and not app_config.enable_change_briefing:
            return t("change_brief_disabled", lang)
        content = assemble_change_briefing(
            self.repository,
            self.llm,
            language=lang,
        )
        return format_change_briefing(content, lang=lang)

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
        if quote is None or quote.price is None:
            quote = ensure_cached_quote(self.repository, symbol)
            state = self.repository.load_state()

        position_value = valuation_for_ticker(portfolio, state, symbol)

        explanation: PriceMoveExplanation | None = None
        if app_config.enable_llm_summaries and quote is not None:
            position = next(
                (
                    item
                    for item in portfolio.positions
                    if item.ticker.strip().upper() == symbol
                ),
                None,
            )
            week_low, week_high = fetch_fifty_two_week_range(symbol)
            ta_snapshot = build_technical_snapshot(symbol)
            news = recent_news_titles_for_ticker(news_cache, symbol, limit=5)
            context = AnalyzeTickerContext(
                ticker=symbol,
                price=quote.price,
                change_pct=quote.change_pct,
                week_52_low=week_low,
                week_52_high=week_high,
                cost_basis=position.cost_basis if position is not None else None,
                pnl_pct=position_value.pl_pct if position_value is not None else None,
                rsi=ta_snapshot.rsi_value if ta_snapshot is not None else None,
                headlines=news,
                language=lang,
            )
            explanation = explain_ticker_for_analyze(
                self.llm,
                context,
                window=window,
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

    def add_ticker_message(
        self,
        chat_id: int,
        ticker: str,
        shares: float = 1.0,
        cost_basis: float | None = None,
    ) -> DeveloperActionReply:
        """Validate and add a ticker to portfolio.json."""
        lang = self._lang(chat_id)
        portfolio_before = self.repository.load_portfolio()
        result = self.repository.add_ticker_to_portfolio(
            ticker,
            shares=shares,
            cost_basis=cost_basis,
        )
        if result.success:
            app_config = self.repository.load_config()
            notified = self._notify_ordinary_portfolio_add(
                result,
                shares_added=shares,
            )
            self._deliver_alerts_after_portfolio_change()
            message = t("add_ticker_ok", lang, message=result.message)
            if result.industry_seeded:
                message = (
                    f"{message}\n"
                    f"{t('add_ticker_industry_seeded', lang, industry=result.industry_seeded)}"
                )
            if result.purchase_cost > 0 and app_config.enable_detailed_cash_display:
                portfolio_after = self.repository.load_portfolio()
                cash_summary = format_cash_balance_text(
                    portfolio_after,
                    lang=lang,
                    include_bookkeeping_note=True,
                    detailed=True,
                )
                message = f"{message}\n\n{cash_summary}"
            if notified:
                message = f"{message}\n{t('users_notified', lang, count=notified)}"
            undo = self._record_completed_portfolio_action(
                chat_id=chat_id,
                action_type="add_ticker",
                portfolio_before=portfolio_before,
                strategy_snapshots=snapshot_strategies(self.repository, [result.ticker]),
                payload={
                    "ticker": result.ticker,
                    "shares": shares,
                    "cost_basis": cost_basis,
                    "is_new_position": result.is_new_position,
                },
                users_notified=notified,
            )
            return DeveloperActionReply(
                text=f"{message}\n\n{undo.text}",
                reply_markup=undo.reply_markup,
            )
        return DeveloperActionReply(t("add_ticker_fail", lang, message=result.message))

    def deposit_cash_message(
        self,
        chat_id: int,
        amount: float,
        *,
        currency: str = "HKD",
        note: str | None = None,
    ) -> DeveloperActionReply:
        """Credit cash to portfolio.json (developer bookkeeping; not shown to ordinary users)."""
        lang = self._lang(chat_id)
        portfolio_before = self.repository.load_portfolio()
        result = self.repository.deposit_cash_to_portfolio(
            amount,
            currency=currency,
        )
        if not result.success:
            return DeveloperActionReply(t("deposit_cash_fail", lang, message=result.message))

        app_config = self.repository.load_config()
        if app_config.enable_detailed_cash_display:
            portfolio_after = self.repository.load_portfolio()
            cash_summary = format_cash_balance_text(
                portfolio_after,
                lang=lang,
                include_bookkeeping_note=True,
                detailed=True,
            )
            message = t(
                "deposit_cash_ok_detailed",
                lang,
                message=result.message,
                cash_summary=cash_summary,
            )
        else:
            message = t(
                "deposit_cash_ok",
                lang,
                message=result.message,
                cash=result.cash_balance_hkd,
            )
        if note:
            message = f"{message}\n{t('deposit_cash_note', lang, note=note)}"

        undo = self._record_completed_portfolio_action(
            chat_id=chat_id,
            action_type="deposit_cash",
            portfolio_before=portfolio_before,
            strategy_snapshots={},
            payload={"amount": amount, "currency": currency, "note": note},
            users_notified=0,
        )
        return DeveloperActionReply(
            text=f"{message}\n\n{undo.text}",
            reply_markup=undo.reply_markup,
        )

    def dev_menu_message(self, chat_id: int) -> DeveloperActionReply:
        """Show the inline developer command hub."""
        lang = self._lang(chat_id)
        from bot.dev_menu import dev_menu_inline_keyboard

        return DeveloperActionReply(
            text=t("dev_menu_intro", lang),
            reply_markup=dev_menu_inline_keyboard(lang=lang),
        )

    def remove_ticker_message(self, chat_id: int, ticker: str) -> DeveloperActionReply:
        """Remove a ticker from portfolio.json."""
        lang = self._lang(chat_id)
        symbol = normalize_ticker(ticker)
        portfolio_before = self.repository.load_portfolio()
        strategies_before = snapshot_strategies(self.repository, [symbol])
        result = self.repository.remove_ticker_from_portfolio(ticker)
        if result.success:
            self.repository.remove_ticker_strategy(ticker)
            notified = self._notify_ordinary_portfolio_remove(symbol)
            self._deliver_alerts_after_portfolio_change()
            message = t("remove_ticker_ok", lang, message=result.message)
            if notified:
                message = f"{message}\n{t('users_notified', lang, count=notified)}"
            undo = self._record_completed_portfolio_action(
                chat_id=chat_id,
                action_type="remove_ticker",
                portfolio_before=portfolio_before,
                strategy_snapshots=strategies_before,
                payload={"ticker": symbol},
                users_notified=notified,
            )
            return DeveloperActionReply(
                text=f"{message}\n\n{undo.text}",
                reply_markup=undo.reply_markup,
            )
        return DeveloperActionReply(t("remove_ticker_fail", lang, message=result.message))

    def _restore_strategy_snapshots(
        self,
        snapshots: dict[str, TickerStrategy],
    ) -> None:
        """Restore strategy records captured before a portfolio mutation."""
        for symbol, strategy in snapshots.items():
            self.repository.upsert_ticker_strategy(
                symbol,
                developer_reasoning=strategy.developer_reasoning,
                strategy_text=strategy.strategy_text,
                shares_at_add=strategy.shares_at_add,
                holding_horizon=strategy.holding_horizon,
                strategy_text_by_language=dict(strategy.strategy_text_by_language),
            )

    def _format_sell_preview(self, parsed: SellParseResult, lang: str) -> str:
        """Build a human-readable sell preview for developer confirmation."""
        shares_to_sell = parsed.shares if parsed.shares is not None else parsed.held_shares
        proceeds = shares_to_sell * parsed.price
        if parsed.shares is None:
            shares_line = t(
                "sell_preview_shares_all",
                lang,
                symbol=parsed.ticker,
                shares=shares_to_sell,
            )
        else:
            shares_line = t(
                "sell_preview_shares_partial",
                lang,
                symbol=parsed.ticker,
                shares=shares_to_sell,
                held=parsed.held_shares,
            )
        lines = [
            t("sell_preview_header", lang, symbol=parsed.ticker),
            "",
            shares_line,
            t("sell_preview_price", lang, price=parsed.price),
            t("sell_preview_proceeds", lang, proceeds=proceeds),
            t("sell_preview_reasoning", lang, reasoning=parsed.reasoning),
        ]
        for warning_key in parsed.warnings:
            lines.extend(
                ["", t(warning_key, lang, symbol=parsed.ticker, value=parsed.price)]
            )
        lines.extend(["", t("sell_preview_confirm_hint", lang)])
        return "\n".join(lines)

    def prepare_sell_ticker(
        self,
        chat_id: int,
        parsed: SellParseResult,
    ) -> DeveloperActionReply:
        """Validate and stage a sell for developer confirmation."""
        lang = self._lang(chat_id)
        portfolio = self.repository.load_portfolio()
        preview = self._format_sell_preview(parsed, lang)
        action = save_pending_action(
            self.repository,
            action_type="sell",
            developer_chat_id=chat_id,
            portfolio_before=portfolio,
            strategy_snapshots=snapshot_strategies(self.repository, [parsed.ticker]),
            payload={
                "ticker": parsed.ticker,
                "shares": parsed.shares,
                "sell_price": parsed.price,
                "reasoning": parsed.reasoning,
            },
        )
        return DeveloperActionReply(
            text=preview,
            reply_markup=confirm_keyboard(
                action.action_id,
                confirm_label=t("portfolio_action_confirm", lang),
                cancel_label=t("portfolio_action_cancel", lang),
            ),
        )

    def confirm_developer_portfolio_action(
        self,
        chat_id: int,
        action_id: str,
    ) -> DeveloperActionReply:
        """Execute a staged developer portfolio action after confirmation."""
        lang = self._lang(chat_id)
        action = load_action(self.repository)
        if (
            action is None
            or action.action_id != action_id
            or action.developer_chat_id != chat_id
            or action.status != "pending_confirm"
        ):
            return DeveloperActionReply(t("portfolio_action_confirm_mismatch", lang))

        if action.action_type == "sell":
            reply_text, notified = self._execute_confirmed_sell(action, lang)
        else:
            return DeveloperActionReply(t("portfolio_action_confirm_mismatch", lang))

        completed = mark_action_completed(
            self.repository,
            action,
            users_notified=notified,
        )
        message = reply_text
        if notified:
            message = f"{message}\n{t('users_notified', lang, count=notified)}"
        message = f"{message}\n\n{t('portfolio_action_undo_hint', lang)}"
        return DeveloperActionReply(
            text=message,
            reply_markup=undo_keyboard(
                completed.action_id,
                undo_label=t("portfolio_action_undo", lang),
            ),
        )

    def cancel_developer_portfolio_action(
        self,
        chat_id: int,
        action_id: str,
    ) -> DeveloperActionReply:
        """Cancel a staged developer portfolio action."""
        lang = self._lang(chat_id)
        action = load_action(self.repository)
        if (
            action is None
            or action.action_id != action_id
            or action.developer_chat_id != chat_id
            or action.status != "pending_confirm"
        ):
            return DeveloperActionReply(t("portfolio_action_confirm_mismatch", lang))
        clear_developer_action(self.repository)
        return DeveloperActionReply(t("portfolio_action_cancelled", lang))

    def undo_developer_portfolio_action(
        self,
        chat_id: int,
        action_id: str,
    ) -> DeveloperActionReply:
        """Reverse the last completed portfolio action and notify users."""
        lang = self._lang(chat_id)
        action = load_action(self.repository)
        if action is None or action.action_id != action_id:
            return DeveloperActionReply(t("portfolio_action_undo_fail", lang))
        if action.developer_chat_id != chat_id:
            return DeveloperActionReply(t("portfolio_action_undo_fail", lang))
        if action.status != "completed":
            return DeveloperActionReply(t("portfolio_action_undo_fail", lang))

        self.repository.save_portfolio(action.portfolio_before.model_copy(deep=True))
        self._restore_strategy_snapshots(action.strategy_snapshots)
        if action.action_type == "add_ticker":
            ticker = str(action.payload.get("ticker", ""))
            if ticker and ticker not in action.strategy_snapshots:
                self.repository.remove_ticker_strategy(ticker)

        notified = 0
        if action.users_notified:
            notified = self._notifier().notify_portfolio_correction(
                self.repository,
                action_type=action.action_type,
                payload=action.payload,
            )
        clear_developer_action(self.repository)
        self._deliver_alerts_after_portfolio_change()

        message = t("portfolio_action_undo_ok", lang)
        if notified:
            message = f"{message}\n{t('users_notified', lang, count=notified)}"
        return DeveloperActionReply(message)

    def undo_last_portfolio_action_message(self, chat_id: int) -> DeveloperActionReply:
        """Undo the stored completed action without an inline button."""
        lang = self._lang(chat_id)
        action = load_action(self.repository)
        if action is None or action.status != "completed":
            return DeveloperActionReply(t("portfolio_action_nothing_to_undo", lang))
        if action.developer_chat_id != chat_id:
            return DeveloperActionReply(t("portfolio_action_undo_fail", lang))
        return self.undo_developer_portfolio_action(chat_id, action.action_id)

    def _execute_confirmed_sell(
        self,
        action: DeveloperPortfolioAction,
        lang: str,
    ) -> tuple[str, int]:
        """Run a confirmed sell and notify ordinary users."""
        symbol = normalize_ticker(str(action.payload.get("ticker", "")))
        sell_price = float(action.payload.get("sell_price", 0))
        reasoning = str(action.payload.get("reasoning", "")).strip()
        shares_raw = action.payload.get("shares")
        shares = float(shares_raw) if shares_raw is not None else None

        result = self.repository.sell_ticker_from_portfolio(
            symbol,
            sell_price=sell_price,
            shares=shares,
        )
        if not result.success:
            clear_developer_action(self.repository)
            return t("sell_ticker_fail", lang, message=result.message), 0

        if result.fully_sold:
            self.repository.remove_ticker_strategy(symbol)

        app_config = self.repository.load_config()
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
        if app_config.enable_detailed_cash_display:
            portfolio_after = self.repository.load_portfolio()
            cash_summary = format_cash_balance_text(
                portfolio_after,
                lang=lang,
                include_bookkeeping_note=True,
                detailed=True,
            )
            message = t(
                "sell_ticker_ok_detailed",
                lang,
                message=result.message,
                cash_summary=cash_summary,
            )
        else:
            message = t(
                "sell_ticker_ok",
                lang,
                message=result.message,
                cash=result.cash_balance_hkd,
            )
        try:
            from storage.performance_ops import save_portfolio_snapshot

            save_portfolio_snapshot(self.repository)
        except Exception:
            logger.exception("Failed to save performance snapshot after sell")
        return message, notified

    def _record_completed_portfolio_action(
        self,
        *,
        chat_id: int,
        action_type: str,
        portfolio_before: Portfolio,
        strategy_snapshots: dict[str, TickerStrategy],
        payload: dict[str, str | float | bool | None],
        users_notified: int,
    ) -> DeveloperActionReply:
        """Store a completed action and return an undo button for the developer."""
        lang = self._lang(chat_id)
        from datetime import UTC, datetime

        from bot.developer_portfolio import new_action_id

        action = DeveloperPortfolioAction(
            action_id=new_action_id(),
            status="completed",
            action_type=action_type,  # type: ignore[arg-type]
            created_at=datetime.now(tz=UTC),
            developer_chat_id=chat_id,
            portfolio_before=portfolio_before.model_copy(deep=True),
            strategy_snapshots=strategy_snapshots,
            payload=payload,
            users_notified=users_notified,
        )
        self.repository.set_developer_portfolio_action(action)
        return DeveloperActionReply(
            text=t("portfolio_action_undo_hint", lang),
            reply_markup=undo_keyboard(
                action.action_id,
                undo_label=t("portfolio_action_undo", lang),
            ),
        )

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
        holding_horizon: str,
        shares: float | None,
        reasoning: str,
        cost_basis: float | None = None,
    ) -> str:
        """Add a holding or save strategy for an existing one, then notify users."""
        lang = self._lang(chat_id)
        app_config = self.repository.load_config()
        portfolio = self.repository.load_portfolio()
        symbol = normalize_ticker(ticker)
        is_new_position = not portfolio_has_ticker(portfolio, symbol)

        if is_new_position:
            add_shares = shares if shares is not None else 1.0
            result = self.repository.add_ticker_to_portfolio(
                ticker,
                shares=add_shares,
                cost_basis=cost_basis,
            )
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
            holding_horizon=holding_horizon,
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
            holding_horizon=holding_horizon,  # type: ignore[arg-type]
            strategy_text_by_language=by_language,
        )

        notified = 0
        cash_suffix = ""
        industry_suffix = ""
        if is_new_position and result.industry_seeded:
            industry_suffix = (
                "\n"
                + t(
                    "add_ticker_industry_seeded",
                    lang,
                    industry=result.industry_seeded,
                )
            )
        if (
            is_new_position
            and result.purchase_cost > 0
            and app_config.enable_detailed_cash_display
        ):
            portfolio_after = self.repository.load_portfolio()
            cash_suffix = (
                "\n\n"
                + format_cash_balance_text(
                    portfolio_after,
                    lang=lang,
                    include_bookkeeping_note=True,
                    detailed=True,
                )
            )
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
            return t(key, lang, symbol=symbol, count=notified) + industry_suffix + cash_suffix

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

    def ta_message(self, chat_id: int, ticker: str) -> tuple[str, bool]:
        """Build a MarkdownV2 TA snapshot or a plain-text error message."""
        lang = self._lang(chat_id)
        symbol = normalize_ticker(ticker)
        validation_error = validate_ticker_format(symbol)
        if validation_error:
            return t("ta_invalid_ticker", lang, symbol=symbol, error=validation_error), False

        snapshot = build_technical_snapshot(symbol)
        if snapshot is None:
            return t("ta_unavailable", lang, symbol=symbol), False
        return format_technical_snapshot(snapshot, lang=lang), True

    def chart_png(
        self,
        chat_id: int,
        ticker: str,
        *,
        period: TickerChartPeriod = "30d",
    ) -> tuple[bytes | None, str]:
        """Render a candlestick chart PNG or return an error message."""
        lang = self._lang(chat_id)
        symbol = normalize_ticker(ticker)
        validation_error = validate_ticker_format(symbol)
        if validation_error:
            return None, t("chart_invalid_ticker", lang, symbol=symbol, error=validation_error)

        png = render_ticker_chart_png(symbol, period=period)
        if png is None:
            return None, t("chart_unavailable", lang, symbol=symbol, period=period)
        return png, ""

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
