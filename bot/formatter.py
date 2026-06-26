"""Message formatting helpers for Telegram delivery."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from collections.abc import Iterator

from analysis.llm import LlmAdvisoryResult
from analysis.move_explainer import PriceMoveExplanation
from analysis.news_summarizer import (
    NewsGroupSummary,
    NewsSummary,
    portfolio_headlines_by_ticker,
    top_important_headlines,
)
from analysis.performance_metrics import PerformanceMetrics
from analysis.portfolio_risk import PortfolioRiskAssessment
from analysis.risk_metrics import RiskMetricsReport
from analysis.technical_snapshot import TechnicalSnapshot
from analysis.portfolio_valuation import (
    PositionValuation,
    PortfolioValuation,
    build_portfolio_valuation,
    infer_quote_currency,
    portfolio_cash_hkd,
    portfolio_total_value_hkd,
)
from analysis.rules import AlertCandidate
from bot.i18n import t
from bot.markdown_v2 import escape_markdown_v2
from storage.models import (
    AppConfig,
    BotState,
    MarketQuote,
    NewsCache,
    PendingAlert,
    PerformanceHistory,
    Portfolio,
    Position,
    TickerSentimentSignal,
    TickerStrategy,
)
from storage.portfolio_ops import normalize_ticker

TELEGRAM_MESSAGE_LIMIT = 4096


def _format_user_date(value: datetime) -> str:
    """Plain calendar date for ordinary users (no ISO time component)."""
    return value.date().isoformat()


def truncate_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> str:
    """Trim long messages to fit Telegram limits."""
    if len(text) <= limit:
        return text
    suffix = "\n\n(message truncated)"
    return text[: limit - len(suffix)] + suffix


def _suggested_action(alert: AlertCandidate, lang: str = "en") -> str:
    if alert.type in {"price_drop", "repeated_negative_news", "rsi_alert", "macd_crossover"} and alert.ticker:
        return t("review", lang, target=alert.ticker)
    if alert.type == "price_rise" and alert.ticker:
        return t("monitor", lang, target=alert.ticker)
    if alert.type == "sector_attention" and alert.industry:
        return t("investigate", lang, target=alert.industry)
    return t("review_monitor", lang)


def _alert_details(alert: AlertCandidate) -> dict[str, float | int | str]:
    return dict(alert.details)


def _urgency_label(urgency: str, lang: str) -> str:
    key = f"alert_urgency_{urgency}"
    return t(key, lang)


def _localized_alert_title(alert: AlertCandidate, lang: str) -> str:
    """Render an alert title in the user's language when structured details exist."""
    details = _alert_details(alert)
    symbol = alert.ticker or ""
    industry = alert.industry or ""

    if alert.type == "price_drop" and "change_pct" in details:
        return t(
            "alert_price_drop_title",
            lang,
            symbol=symbol,
            pct=details["change_pct"],
        )
    if alert.type == "price_rise" and "change_pct" in details:
        return t(
            "alert_price_rise_title",
            lang,
            symbol=symbol,
            pct=details["change_pct"],
        )
    if alert.type == "repeated_negative_news" and symbol:
        return t("alert_negative_news_title", lang, symbol=symbol)
    if alert.type == "sector_attention" and industry:
        return t("alert_sector_title", lang, industry=industry)
    if alert.type == "rsi_alert" and symbol and {"signal", "rsi"} <= details.keys():
        return t(
            "alert_rsi_title",
            lang,
            symbol=symbol,
            signal=details["signal"],
            rsi=details["rsi"],
        )
    if alert.type == "macd_crossover" and symbol and {"signal", "macd"} <= details.keys():
        return t(
            "alert_macd_title",
            lang,
            symbol=symbol,
            signal=details["signal"],
        )
    return alert.title


def _localized_alert_explanation(alert: AlertCandidate, lang: str) -> str:
    """Render an alert explanation in the user's language when structured details exist."""
    details = _alert_details(alert)
    symbol = alert.ticker or ""
    industry = alert.industry or ""

    if alert.type == "price_drop" and {"change_pct", "threshold"} <= details.keys():
        return t(
            "alert_price_drop_explanation",
            lang,
            symbol=symbol,
            pct=details["change_pct"],
            threshold=details["threshold"],
        )
    if alert.type == "price_rise" and {"change_pct", "threshold"} <= details.keys():
        return t(
            "alert_price_rise_explanation",
            lang,
            symbol=symbol,
            pct=details["change_pct"],
            threshold=details["threshold"],
        )
    if alert.type == "repeated_negative_news" and {"count", "hours"} <= details.keys():
        return t(
            "alert_negative_news_explanation",
            lang,
            symbol=symbol,
            count=details["count"],
            hours=details["hours"],
        )
    if alert.type == "sector_attention" and {"count", "hours"} <= details.keys():
        return t(
            "alert_sector_explanation",
            lang,
            industry=industry,
            count=details["count"],
            hours=details["hours"],
        )
    if alert.type == "rsi_alert" and {"signal", "rsi"} <= details.keys():
        return t(
            "alert_rsi_explanation",
            lang,
            symbol=symbol,
            signal=details["signal"],
            rsi=details["rsi"],
        )
    if alert.type == "macd_crossover" and {"signal", "macd", "macd_signal"} <= details.keys():
        return t(
            "alert_macd_explanation",
            lang,
            symbol=symbol,
            signal=details["signal"],
            macd=details["macd"],
            macd_signal=details["macd_signal"],
        )
    return alert.explanation


def _localized_alert_line(alert: AlertCandidate, lang: str) -> str:
    """One-line alert summary for digests and /analyze."""
    target = alert.ticker or alert.industry or t("alert_target_na", lang)
    return t(
        "alert_summary_line",
        lang,
        urgency=_urgency_label(alert.urgency, lang),
        title=_localized_alert_title(alert, lang),
        target=target,
    )


def format_urgent_alert(
    alert: AlertCandidate,
    *,
    lang: str = "en",
    llm_explanation: str | None = None,
) -> str:
    """Format an urgent alert for Telegram delivery."""
    target = alert.ticker or alert.industry or "portfolio"
    explanation_text = llm_explanation if llm_explanation is not None else alert.llm_explanation
    lines = [
        t("urgent_alert", lang),
        _localized_alert_title(alert, lang),
        f"{t('target', lang)}: {target}",
        _localized_alert_explanation(alert, lang),
    ]
    if explanation_text:
        lines.extend(["", explanation_text])
    lines.append(f"{t('suggested', lang)}: {_suggested_action(alert, lang)}.")
    return truncate_message("\n".join(lines))


def format_informational_alert(alert: AlertCandidate, *, lang: str = "en") -> str:
    """Format a non-urgent alert for Telegram delivery."""
    target = alert.ticker or alert.industry or "portfolio"
    lines = [
        t(
            "alert_nonurgent_header",
            lang,
            urgency=_urgency_label(alert.urgency, lang),
        ),
        _localized_alert_title(alert, lang),
        f"{t('target', lang)}: {target}",
        _localized_alert_explanation(alert, lang),
    ]
    if alert.llm_explanation:
        lines.extend(["", alert.llm_explanation])
    return truncate_message("\n".join(lines))


def _append_news_summary_sections(
    lines: list[str],
    news_summary: NewsSummary,
    *,
    lang: str = "en",
) -> None:
    """Append sector and ticker news blocks to a message."""
    if news_summary.sector_summaries:
        lines.extend([t("news_by_sector", lang), ""])
        for sector, summary in news_summary.sector_summaries.items():
            lines.append(f"{sector}:")
            lines.append(summary)
            lines.append("")

    if news_summary.ticker_summaries:
        lines.extend([t("news_by_ticker", lang), ""])
        for ticker, summary in news_summary.ticker_summaries.items():
            lines.append(f"{ticker}:")
            lines.append(summary)
            lines.append("")


def format_daily_news_brief(
    news_summary: NewsSummary | None,
    *,
    portfolio: Portfolio | None = None,
    news_cache: NewsCache | None = None,
    app_config: AppConfig | None = None,
    ticker_to_industry: dict[str, str] | None = None,
    lang: str = "en",
) -> str:
    """Render top headlines and optional LLM digests for the daily summary."""
    lines: list[str] = []

    if (
        portfolio is not None
        and news_cache is not None
        and app_config is not None
        and ticker_to_industry is not None
    ):
        top_lines = _format_top_headlines_lines(
            portfolio,
            news_cache,
            app_config,
            ticker_to_industry,
            lang=lang,
        )
        if top_lines:
            lines.extend(top_lines)
            lines.append("")

    if news_summary is not None and news_summary.ticker_summaries:
        lines.extend([t("daily_news_digest_title", lang), ""])
        for ticker, summary in news_summary.ticker_summaries.items():
            lines.append(f"{ticker}:")
            lines.append(summary.strip())
            lines.append("")

    return "\n".join(lines).strip()


def _format_news_group_message(label: str, summary: str) -> str:
    """Format one sector or ticker summary block."""
    return truncate_message(f"{label}:\n{summary}")


def iter_format_news_summary_messages(
    groups: Iterator[NewsGroupSummary],
    *,
    lang: str = "en",
) -> Iterator[str]:
    """Yield Telegram messages for /news_summary as each group is ready."""
    yield t("news_summary_title", lang)

    sector_header_sent = False
    ticker_header_sent = False
    content_count = 0

    for group in groups:
        if group.kind == "sector":
            if not sector_header_sent:
                yield t("news_by_sector", lang)
                sector_header_sent = True
            yield _format_news_group_message(group.label, group.text)
            content_count += 1
            continue

        if not ticker_header_sent:
            yield t("news_by_ticker", lang)
            ticker_header_sent = True
        yield _format_news_group_message(group.label, group.text)
        content_count += 1

    if content_count == 0:
        yield t("news_summary_empty", lang)


def format_news_summary_messages(
    news_summary: NewsSummary,
    *,
    lang: str = "en",
) -> list[str]:
    """Split /news_summary output into multiple Telegram-sized messages."""
    messages: list[str] = [t("news_summary_title", lang)]

    if news_summary.sector_summaries:
        messages.append(t("news_by_sector", lang))
        for sector, summary in news_summary.sector_summaries.items():
            messages.append(_format_news_group_message(sector, summary))

    if news_summary.ticker_summaries:
        messages.append(t("news_by_ticker", lang))
        for ticker, summary in news_summary.ticker_summaries.items():
            messages.append(_format_news_group_message(ticker, summary))

    if len(messages) == 1:
        messages.append(t("news_summary_empty", lang))

    footer = t("news_footer", lang)
    messages[-1] = truncate_message(f"{messages[-1]}\n\n{footer}")
    return messages


def format_news_summary(news_summary: NewsSummary, *, lang: str = "en") -> str:
    """Render on-demand /news_summary output as a single string (tests/helpers)."""
    return "\n\n".join(format_news_summary_messages(news_summary, lang=lang))


def _append_hkd_valuation_lines(
    lines: list[str],
    valuation: PositionValuation,
    lang: str,
    *,
    include_weight: bool = True,
) -> None:
    """Append HKD value, weight, and P/L lines for one holding."""
    if valuation.market_value_hkd is not None:
        lines.append(
            t("portfolio_value_hkd", lang, value=valuation.market_value_hkd)
        )
    if include_weight and valuation.weight_pct is not None:
        lines.append(t("portfolio_weight", lang, weight=valuation.weight_pct))
    if valuation.pl_hkd is not None and valuation.pl_pct is not None:
        lines.append(
            t(
                "portfolio_pl_hkd",
                lang,
                amount=valuation.pl_hkd,
                pct=valuation.pl_pct,
            )
        )


def _append_portfolio_totals_hkd(
    lines: list[str],
    valuation: PortfolioValuation,
    lang: str,
) -> None:
    """Append portfolio-wide HKD totals."""
    lines.append(
        t(
            "portfolio_total_value_hkd",
            lang,
            value=valuation.total_market_value_hkd,
        )
    )
    if valuation.total_pl_hkd is not None and valuation.total_pl_pct is not None:
        lines.append(
            t(
                "portfolio_total_pl_hkd",
                lang,
                amount=valuation.total_pl_hkd,
                pct=valuation.total_pl_pct,
            )
        )
    elif any(position.cost_value_hkd is None for position in valuation.positions):
        lines.append(t("portfolio_total_pl_partial", lang))


def _format_performance_pct(value: float | None, lang: str) -> str:
    if value is None:
        return t("performance_na", lang)
    return f"{value:+.2f}%"


def format_performance_lines(metrics: PerformanceMetrics, *, lang: str = "en") -> list[str]:
    """Shared performance metrics lines for /performance and daily summary."""
    return [
        t("performance_line_current_value", lang, value=metrics.current_value),
        t(
            "performance_line_return_7d",
            lang,
            pct=_format_performance_pct(metrics.return_7d_pct, lang),
        ),
        t(
            "performance_line_return_30d",
            lang,
            pct=_format_performance_pct(metrics.return_30d_pct, lang),
        ),
        t(
            "performance_line_return_all_time",
            lang,
            pct=_format_performance_pct(metrics.return_all_time_pct, lang),
        ),
        t(
            "performance_line_max_drawdown",
            lang,
            pct=_format_performance_pct(metrics.max_drawdown_pct, lang),
        ),
    ]


def format_performance(metrics: PerformanceMetrics, *, lang: str = "en") -> str:
    """Render portfolio return windows and max drawdown."""
    lines = [t("performance_title", lang), ""]
    lines.extend(format_performance_lines(metrics, lang=lang))
    lines.append("")
    lines.append(
        t("performance_line_snapshots", lang, count=metrics.snapshot_count)
    )
    return truncate_message("\n".join(lines))


def _format_risk_metric_value(value: float | None, *, lang: str, decimals: int = 2) -> str:
    if value is None:
        return t("performance_na", lang)
    return f"{value:.{decimals}f}"


def format_risk_metrics(report: RiskMetricsReport, *, lang: str = "en") -> str:
    """Render on-demand historical risk metrics vs a benchmark."""
    lines = [
        t("risk_metrics_title", lang),
        t(
            "risk_metrics_window",
            lang,
            days=report.observation_days,
            benchmark=report.benchmark_ticker,
        ),
        "",
        t(
            "risk_metrics_sharpe",
            lang,
            value=_format_risk_metric_value(report.sharpe_ratio, lang=lang),
        ),
        t(
            "risk_metrics_max_drawdown",
            lang,
            value=_format_risk_metric_value(report.max_drawdown_pct, lang=lang),
        ),
        t(
            "risk_metrics_portfolio_return",
            lang,
            value=_format_risk_metric_value(report.portfolio_return_pct, lang=lang),
        ),
        t(
            "risk_metrics_benchmark_return",
            lang,
            benchmark=report.benchmark_ticker,
            value=_format_risk_metric_value(report.benchmark_return_pct, lang=lang),
        ),
        t(
            "risk_metrics_alpha",
            lang,
            value=_format_risk_metric_value(report.alpha_pct, lang=lang),
        ),
        "",
        t("risk_metrics_footer", lang),
    ]
    return truncate_message("\n".join(lines))


def format_technical_snapshot(snapshot: TechnicalSnapshot, *, lang: str = "en") -> str:
    """Render a ticker TA snapshot for Telegram MarkdownV2."""
    esc = escape_markdown_v2
    symbol = esc(snapshot.ticker)
    rsi_label = esc(t(f"ta_rsi_{snapshot.rsi_label}", lang))
    macd_label = esc(t(f"ta_macd_{snapshot.macd_status}", lang))
    sma_label = esc(t(f"ta_sma_{snapshot.sma_status}", lang))
    bb_label = esc(t(f"ta_bb_{snapshot.bollinger_status}", lang))
    close_text = esc(f"{snapshot.close_price:.2f}")
    rsi_value = esc(f"{snapshot.rsi_value:.1f}")

    return "\n".join(
        [
            f"*{esc('📊')} {symbol} — {esc(t('ta_title', lang))}*",
            "",
            f"📊 RSI\\(14\\): *{rsi_value}* \\({rsi_label}\\)",
            f"📉 MACD: *{macd_label}*",
            f"📈 SMA20 vs SMA50: *{sma_label}*",
            f"🕯 Price vs Bollinger Bands: *{bb_label}*",
            "",
            f"_{esc(t('ta_last_close', lang))}: {close_text}_",
        ]
    )


def format_weekly_summary(
    portfolio: Portfolio,
    *,
    state: BotState | None = None,
    performance_history: PerformanceHistory | None = None,
    lang: str = "en",
) -> str:
    """Format the Monday weekly summary focused on portfolio performance."""
    lines = [t("weekly_summary_title", lang), ""]

    if state is not None and (portfolio.positions or portfolio_cash_hkd(portfolio) > 0):
        lines.append(
            t("weekly_summary_holdings", lang, holdings=len(portfolio.positions))
        )
        if portfolio.positions:
            valuation = build_portfolio_valuation(portfolio, state)
            total_value = portfolio_total_value_hkd(portfolio, valuation)
            lines.append(
                t("daily_portfolio_value_hkd", lang, value=total_value)
            )
            if valuation.total_pl_hkd is not None and valuation.total_pl_pct is not None:
                lines.append(
                    t(
                        "daily_portfolio_pl_hkd",
                        lang,
                        amount=valuation.total_pl_hkd,
                        pct=valuation.total_pl_pct,
                    )
                )
        elif portfolio_cash_hkd(portfolio) > 0:
            lines.append(
                t(
                    "daily_portfolio_value_hkd",
                    lang,
                    value=portfolio_cash_hkd(portfolio),
                )
            )

    if performance_history is not None:
        from analysis.performance_metrics import compute_performance_metrics

        metrics = compute_performance_metrics(performance_history)
        if metrics is not None:
            lines.append("")
            lines.append(t("weekly_performance_header", lang))
            lines.extend(format_performance_lines(metrics, lang=lang))

    lines.append("")
    lines.append(t("advisory_footer", lang))
    return truncate_message("\n".join(lines))


def format_daily_summary(
    portfolio: Portfolio,
    alerts: list[AlertCandidate],
    advisory: LlmAdvisoryResult | None,
    app_config: AppConfig,
    news_summary: NewsSummary | None = None,
    *,
    state: BotState | None = None,
    news_cache: NewsCache | None = None,
    ticker_to_industry: dict[str, str] | None = None,
    performance_history: PerformanceHistory | None = None,
    lang: str = "en",
) -> str:
    """Format a concise daily summary for Telegram delivery."""
    _ = advisory
    visible_alerts = _visible_alerts(alerts, app_config)
    lines = [
        t("daily_summary", lang),
        t(
            "holdings_alerts",
            lang,
            holdings=len(portfolio.positions),
            alerts=len(visible_alerts),
        ),
    ]

    if state is not None and portfolio.positions:
        valuation = build_portfolio_valuation(portfolio, state)
        total_value = portfolio_total_value_hkd(portfolio, valuation)
        lines.append(
            t(
                "daily_portfolio_value_hkd",
                lang,
                value=total_value,
            )
        )
        if valuation.total_pl_hkd is not None and valuation.total_pl_pct is not None:
            lines.append(
                t(
                    "daily_portfolio_pl_hkd",
                    lang,
                    amount=valuation.total_pl_hkd,
                    pct=valuation.total_pl_pct,
                )
            )

    if performance_history is not None:
        from analysis.performance_metrics import compute_performance_metrics

        metrics = compute_performance_metrics(performance_history)
        if metrics is not None:
            lines.append("")
            lines.append(t("performance_section_header", lang))
            lines.extend(format_performance_lines(metrics, lang=lang))

    lines.append("")

    if visible_alerts:
        lines.append(t("alerts_header", lang))
        for alert in visible_alerts[:3]:
            lines.append(_localized_alert_line(alert, lang))
        if len(visible_alerts) > 3:
            lines.append(t("plus_more", lang, count=len(visible_alerts) - 3))
        lines.append("")

    brief = format_daily_news_brief(
        news_summary,
        portfolio=portfolio,
        news_cache=news_cache,
        app_config=app_config,
        ticker_to_industry=ticker_to_industry,
        lang=lang,
    )
    if brief:
        lines.extend(["", brief])

    lines.append(t("advisory_footer", lang))
    return truncate_message("\n".join(lines))


def format_start(*, lang: str = "en", is_developer: bool = False) -> str:
    """Welcome message for /start."""
    lines = [
        t("welcome_title", lang),
        "",
        t("welcome_greeting", lang),
        "",
        t("welcome_features", lang),
        "",
        t("welcome_quick_start", lang),
        "",
        t("welcome_tip", lang),
        "",
        t("advisory_footer", lang),
    ]
    if is_developer:
        lines.extend(["", t("welcome_dev_extra", lang)])
    return "\n".join(lines)


def _horizon_label(horizon: str, lang: str) -> str:
    """Return a localized long/short horizon label."""
    if horizon == "short":
        return t("horizon_label_short", lang)
    return t("horizon_label_long", lang)


def _position_horizon(
    position: Position,
    strategies: dict[str, TickerStrategy] | None,
) -> str:
    """Resolve the holding horizon for one portfolio position."""
    symbol = position.ticker.strip().upper()
    if strategies and symbol in strategies:
        return strategies[symbol].holding_horizon
    return "long"


def _group_positions_by_horizon(
    portfolio: Portfolio,
    strategies: dict[str, TickerStrategy] | None,
) -> tuple[list[Position], list[Position]]:
    """Split portfolio positions into long-term and short-term lists."""
    long_positions: list[Position] = []
    short_positions: list[Position] = []
    for position in portfolio.positions:
        if _position_horizon(position, strategies) == "short":
            short_positions.append(position)
        else:
            long_positions.append(position)
    return long_positions, short_positions


def _append_portfolio_position_lines(
    lines: list[str],
    position: Position,
    state: BotState,
    by_ticker: dict[str, PositionValuation],
    *,
    lang: str,
    is_developer: bool,
    strategies: dict[str, TickerStrategy] | None,
) -> None:
    """Append formatted lines for a single portfolio holding."""
    symbol = position.ticker.strip().upper()
    horizon = _position_horizon(position, strategies)
    lines.append(
        t(
            "portfolio_shares_horizon",
            lang,
            symbol=symbol,
            shares=position.shares,
            horizon=_horizon_label(horizon, lang),
        )
    )
    if position.cost_basis is not None:
        lines.append(t("portfolio_cost_basis", lang, value=position.cost_basis))

    quote = state.latest_prices.get(symbol)
    position_value = by_ticker.get(symbol)
    if quote is None or quote.price is None:
        lines.append(t("portfolio_price_unavailable", lang))
    else:
        change = (
            f"{quote.change_pct:+.2f}%"
            if quote.change_pct is not None
            else "n/a"
        )
        label = quote.company_name or symbol
        currency = infer_quote_currency(quote, symbol)
        lines.append(
            t(
                "portfolio_last_price_ccy",
                lang,
                price=quote.price,
                currency=currency,
                change=change,
            )
        )
        lines.append(t("portfolio_company", lang, name=label))
        if quote.fetched_at:
            if is_developer:
                lines.append(
                    t(
                        "portfolio_quote_as_of",
                        lang,
                        timestamp=quote.fetched_at.isoformat(),
                    )
                )
            else:
                lines.append(
                    t(
                        "portfolio_quote_as_of_user",
                        lang,
                        date=_format_user_date(quote.fetched_at),
                    )
                )
    if position_value is not None:
        _append_hkd_valuation_lines(lines, position_value, lang)
    if position.notes:
        lines.append(t("portfolio_position_notes", lang, notes=position.notes))
    lines.append("")


def format_help(*, lang: str = "en", is_developer: bool = False) -> str:
    """Help text for /help."""
    lines = [t("help_header", lang), "", t("help_commands", lang)]
    if is_developer:
        lines.extend(["", t("help_dev_commands", lang)])
    return "\n".join(lines)


def format_portfolio(
    portfolio: Portfolio,
    state: BotState,
    *,
    strategies: dict[str, TickerStrategy] | None = None,
    lang: str = "en",
    is_developer: bool = False,
) -> str:
    """Render portfolio holdings with latest market quotes."""
    if not portfolio.positions:
        key = "portfolio_empty_dev" if is_developer else "portfolio_empty"
        return t(key, lang)

    valuation = build_portfolio_valuation(portfolio, state)
    by_ticker = {item.ticker: item for item in valuation.positions}
    long_positions, short_positions = _group_positions_by_horizon(portfolio, strategies)

    lines = [t("portfolio_header", lang, count=len(portfolio.positions)), ""]

    if long_positions:
        lines.append(t("portfolio_section_long", lang))
        lines.append("")
        for position in long_positions:
            _append_portfolio_position_lines(
                lines,
                position,
                state,
                by_ticker,
                lang=lang,
                is_developer=is_developer,
                strategies=strategies,
            )

    if short_positions:
        lines.append(t("portfolio_section_short", lang))
        lines.append("")
        for position in short_positions:
            _append_portfolio_position_lines(
                lines,
                position,
                state,
                by_ticker,
                lang=lang,
                is_developer=is_developer,
                strategies=strategies,
            )

    if portfolio.notes:
        lines.extend([t("portfolio_notes_header", lang), portfolio.notes])

    lines.append("")
    _append_portfolio_totals_hkd(lines, valuation, lang)
    cash_hkd = portfolio_cash_hkd(portfolio, usd_to_hkd=valuation.usd_to_hkd)
    if is_developer and cash_hkd > 0:
        cash_parts: list[str] = []
        if portfolio.cash > 0:
            cash_parts.append(f"{portfolio.cash:,.2f} HKD")
        if portfolio.cash_usd > 0:
            cash_parts.append(f"{portfolio.cash_usd:,.2f} USD")
        if portfolio.cash_jpy > 0:
            cash_parts.append(f"{portfolio.cash_jpy:,.0f} JPY")
        if len(cash_parts) > 1 or portfolio.cash_usd > 0 or portfolio.cash_jpy > 0:
            lines.append(
                t(
                    "portfolio_cash_multi",
                    lang,
                    breakdown=" + ".join(cash_parts),
                    total_hkd=cash_hkd,
                )
            )
        else:
            lines.append(t("portfolio_cash", lang, cash=portfolio.cash))
        lines.append(
            t(
                "portfolio_grand_total_hkd",
                lang,
                value=portfolio_total_value_hkd(portfolio, valuation),
            )
        )

    if state.last_market_fetch_at:
        if is_developer:
            lines.extend(
                [
                    "",
                    t(
                        "portfolio_last_fetch",
                        lang,
                        timestamp=state.last_market_fetch_at.isoformat(),
                    ),
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    t(
                        "portfolio_last_fetch_user",
                        lang,
                        date=_format_user_date(state.last_market_fetch_at),
                    ),
                ]
            )

    return truncate_message("\n".join(lines).strip())


def format_industries(
    focus_industries: list[str],
    news_cache: NewsCache,
    *,
    lang: str = "en",
    is_developer: bool = False,
) -> str:
    """Render focus industries with recent tagged news counts."""
    if not focus_industries:
        key = "industries_empty" if is_developer else "industries_empty_user"
        return t(key, lang)

    lines = [t("industries_header", lang), ""]
    for industry in focus_industries:
        label = industry.strip()
        if not label:
            continue
        count = sum(1 for item in news_cache.items if label in item.sector_tags)
        if is_developer:
            lines.append(t("industries_line", lang, label=label, count=count))
        elif count == 0:
            lines.append(t("industries_line_none_user", lang, label=label))
        else:
            lines.append(t("industries_line_user", lang, label=label, count=count))

    if is_developer:
        lines.extend(["", t("industries_total", lang, count=len(news_cache.items))])
        if news_cache.updated_at:
            lines.append(
                t(
                    "industries_updated",
                    lang,
                    timestamp=news_cache.updated_at.isoformat(),
                )
            )
    else:
        lines.extend(
            ["", t("industries_total_user", lang, count=len(news_cache.items))]
        )
        if news_cache.updated_at:
            lines.append(
                t(
                    "industries_updated_user",
                    lang,
                    date=_format_user_date(news_cache.updated_at),
                )
            )

    return truncate_message("\n".join(lines))


def format_analyze(
    alerts: list[AlertCandidate],
    advisory: LlmAdvisoryResult | None,
    app_config: AppConfig,
    *,
    portfolio: Portfolio | None = None,
    sentiment_by_ticker: dict[str, TickerSentimentSignal] | None = None,
    news_cache: NewsCache | None = None,
    ticker_to_industry: dict[str, str] | None = None,
    risk: PortfolioRiskAssessment | None = None,
    lang: str = "en",
    is_developer: bool = False,
) -> str:
    """Render rule alerts and optional LLM advisory output."""
    visible_alerts = _visible_alerts(alerts, app_config)
    lines = [t("analyze_header", lang), ""]

    if risk is not None:
        lines.extend(_format_risk_lines(risk, lang))
        lines.append("")

    if visible_alerts:
        lines.append(t("analyze_alerts_count", lang, count=len(visible_alerts)))
        for alert in visible_alerts:
            lines.append(_localized_alert_line(alert, lang))
            lines.append(f"  {_localized_alert_explanation(alert, lang)}")
        lines.append("")
    else:
        lines.extend([t("analyze_no_alerts", lang), ""])

    if portfolio is not None and news_cache is not None:
        headline_lines = _format_portfolio_headlines_lines(
            portfolio,
            news_cache,
            app_config,
            lang=lang,
        )
        if headline_lines:
            lines.extend(headline_lines)
            lines.append("")

    sentiment_lines = _format_analyze_sentiment_lines(
        portfolio,
        sentiment_by_ticker,
        lang=lang,
    )
    if sentiment_lines:
        lines.extend(sentiment_lines)
        lines.append("")

    if app_config.enable_llm_summaries:
        if advisory is None:
            key = "analyze_llm_empty" if is_developer else "analyze_llm_empty_user"
            lines.append(t(key, lang))
        else:
            if is_developer:
                lines.extend(
                    [
                        t(
                            "analyze_llm_header",
                            lang,
                            source=advisory.source,
                            urgency=advisory.urgency,
                        ),
                        advisory.summary,
                    ]
                )
            else:
                lines.extend([t("advisory", lang), advisory.summary])
            if advisory.suggested_actions:
                actions = "; ".join(advisory.suggested_actions)
                lines.append(t("analyze_suggested", lang, actions=actions))
            if advisory.error and is_developer:
                lines.append(t("analyze_llm_note", lang, note=advisory.error))
    else:
        key = "analyze_llm_disabled" if is_developer else "analyze_llm_disabled_user"
        lines.append(t(key, lang))

    return truncate_message("\n".join(lines))


def _format_analyze_sentiment_lines(
    portfolio: Portfolio | None,
    sentiment_by_ticker: dict[str, TickerSentimentSignal] | None,
    *,
    lang: str,
) -> list[str]:
    """Build news-sentiment section for /analyze (one line per holding)."""
    if portfolio is None or not portfolio.positions:
        return []

    sentiment = sentiment_by_ticker or {}
    lines: list[str] = []
    for position in portfolio.positions:
        symbol = normalize_ticker(position.ticker)
        record = sentiment.get(symbol)
        if record is None:
            lines.append(t("analyze_sentiment_line_none", lang, symbol=symbol))
        else:
            lines.append(
                t(
                    "analyze_sentiment_line",
                    lang,
                    symbol=symbol,
                    score=record.score,
                    count=record.article_count,
                )
            )

    return [t("analyze_sentiment_header", lang), *lines]


def _visible_alerts(
    alerts: list[AlertCandidate],
    app_config: AppConfig,
) -> list[AlertCandidate]:
    """Hide sector-attention alerts unless explicitly enabled in config."""
    if app_config.enable_sector_attention_alerts:
        return alerts
    return [alert for alert in alerts if alert.type != "sector_attention"]


def _format_top_headlines_lines(
    portfolio: Portfolio,
    news_cache: NewsCache,
    app_config: AppConfig,
    ticker_to_industry: dict[str, str],
    *,
    lang: str,
) -> list[str]:
    """Build ranked top headlines from all cached articles (macro excluded)."""
    ranked = top_important_headlines(
        portfolio,
        news_cache,
        app_config,
        ticker_to_industry,
    )
    if not ranked:
        return []

    lines = [t("daily_top_headlines_title", lang), ""]
    for row in ranked:
        lines.append(f"• [{row.label}] {row.item.title.strip()}")
    return lines


def _format_risk_lines(risk: PortfolioRiskAssessment, lang: str) -> list[str]:
    """Format portfolio risk level, score, and contributing factors."""
    lines = [
        t(
            "analyze_risk_header",
            lang,
            level=t(f"risk_level_{risk.level}", lang),
            score=risk.score,
        ),
    ]
    if risk.within_limits:
        lines.append(t("analyze_risk_within_limits", lang))
    else:
        lines.append(t("analyze_risk_above_limits", lang))
    for factor in risk.factors:
        lines.append(t("analyze_risk_factor", lang, detail=factor))
    return lines


def _format_portfolio_headlines_lines(
    portfolio: Portfolio,
    news_cache: NewsCache,
    app_config: AppConfig,
    *,
    lang: str,
) -> list[str]:
    """Build deduplicated headline bullets for each holding."""
    headlines = portfolio_headlines_by_ticker(portfolio, news_cache, app_config)
    if not headlines:
        return []

    lines = [t("portfolio_headlines_header", lang), ""]
    for symbol in sorted(headlines):
        lines.append(f"{symbol}:")
        for item in headlines[symbol]:
            lines.append(f"• {item.title.strip()}")
        lines.append("")
    return lines


def format_pros_cons_analysis(
    memos_by_ticker: dict[str, str],
    *,
    generated_for: str | None = None,
    lang: str = "en",
) -> str:
    """Render cached or freshly generated pros/cons memos."""
    if not memos_by_ticker:
        return t("analyze_pros_empty", lang)

    lines = [t("analyze_pros_header", lang), ""]
    for symbol in sorted(memos_by_ticker):
        lines.extend([f"{symbol}:", memos_by_ticker[symbol].strip(), ""])

    if generated_for:
        lines.append(t("analyze_pros_generated", lang, symbol=generated_for))
    else:
        lines.append(t("analyze_pros_cached", lang))

    lines.append(t("advisory_footer", lang))
    return truncate_message("\n".join(lines))


def format_ticker_analysis(
    ticker: str,
    quote: MarketQuote | None,
    window: str,
    explanation: PriceMoveExplanation | None,
    app_config: AppConfig,
    *,
    position_valuation: PositionValuation | None = None,
    lang: str = "en",
    is_developer: bool = False,
) -> str:
    symbol = ticker.strip().upper()
    lines = [t("ticker_header", lang, symbol=symbol), ""]

    if quote is None or quote.price is None:
        lines.append(t("ticker_no_price", lang))
        return truncate_message("\n".join(lines))

    change = (
        f"{quote.change_pct:+.2f}%"
        if quote.change_pct is not None
        else "n/a"
    )
    label = quote.company_name or symbol
    lines.append(t("ticker_company", lang, name=label))
    currency = infer_quote_currency(quote, symbol)
    lines.append(
        t(
            "ticker_last_price_ccy",
            lang,
            price=quote.price,
            currency=currency,
            change=change,
            window=window,
        )
    )
    if position_valuation is not None and position_valuation.market_value_hkd is not None:
        lines.append(
            t(
                "ticker_value_hkd",
                lang,
                shares=position_valuation.shares,
                value=position_valuation.market_value_hkd,
            )
        )
        if position_valuation.pl_hkd is not None and position_valuation.pl_pct is not None:
            lines.append(
                t(
                    "ticker_pl_hkd",
                    lang,
                    amount=position_valuation.pl_hkd,
                    pct=position_valuation.pl_pct,
                )
            )
    if quote.sector:
        lines.append(t("ticker_sector", lang, sector=quote.sector))
    lines.append("")

    if not app_config.enable_llm_summaries:
        key = "ticker_llm_disabled" if is_developer else "ticker_llm_disabled_user"
        lines.append(t(key, lang))
    elif explanation is None:
        key = "ticker_llm_empty" if is_developer else "ticker_llm_empty_user"
        lines.append(t(key, lang))
    else:
        lines.append(explanation.to_message(lang))

    return truncate_message("\n".join(lines))


def _pending_alert_type(alert: PendingAlert) -> str:
    """Resolve alert type for legacy pending alerts missing the type field."""
    if alert.type in {
        "price_drop",
        "price_rise",
        "repeated_negative_news",
        "sector_attention",
    }:
        return alert.type
    if alert.industry:
        return "sector_attention"
    if alert.related_tickers:
        return "price_drop"
    return "sector_attention"


def format_alert(alert: PendingAlert, *, lang: str = "en") -> str:
    """Render a pending alert using the appropriate Telegram template."""
    if ":" in alert.message:
        title, explanation = alert.message.split(":", 1)
        title = title.strip()
        explanation = explanation.strip()
    else:
        title = alert.message.strip()
        explanation = ""

    candidate = AlertCandidate(
        id=alert.id,
        type=_pending_alert_type(alert),  # type: ignore[arg-type]
        ticker=alert.related_tickers[0] if alert.related_tickers else None,
        industry=alert.industry,
        urgency=alert.severity,
        title=title,
        explanation=explanation,
        created_at=alert.created_at,
        llm_explanation=alert.llm_explanation,
        details=alert.details,
    )
    if alert.severity == "urgent":
        return format_urgent_alert(candidate, lang=lang)
    return format_informational_alert(candidate, lang=lang)


def _append_strategy_list_items(
    lines: list[str],
    positions: list[Position],
    strategies: dict[str, TickerStrategy],
    localized: dict[str, str],
    *,
    lang: str,
) -> None:
    """Append strategy list lines for one horizon group."""
    for position in positions:
        symbol = position.ticker.strip().upper()
        strategy = strategies.get(symbol)
        if strategy is None:
            lines.append(t("strategy_list_missing", lang, symbol=symbol))
            continue
        preview = localized.get(symbol, strategy.strategy_text).replace("\n", " ").strip()
        if len(preview) > 120:
            preview = preview[:117].rstrip() + "..."
        lines.append(
            t(
                "strategy_list_item_horizon",
                lang,
                symbol=symbol,
                horizon=_horizon_label(strategy.holding_horizon, lang),
                preview=preview,
            )
        )


def format_strategy_list(
    portfolio: Portfolio,
    strategies: dict[str, TickerStrategy],
    *,
    display_by_ticker: dict[str, str] | None = None,
    lang: str = "en",
) -> str:
    """List portfolio tickers and whether a stored strategy exists."""
    if not portfolio.positions:
        return t("strategy_portfolio_empty", lang)

    localized = display_by_ticker or {}
    long_positions, short_positions = _group_positions_by_horizon(portfolio, strategies)
    lines = [t("strategy_list_header", lang), ""]

    if long_positions:
        lines.append(t("portfolio_section_long", lang))
        lines.append("")
        _append_strategy_list_items(
            lines,
            long_positions,
            strategies,
            localized,
            lang=lang,
        )
        lines.append("")

    if short_positions:
        lines.append(t("portfolio_section_short", lang))
        lines.append("")
        _append_strategy_list_items(
            lines,
            short_positions,
            strategies,
            localized,
            lang=lang,
        )
        lines.append("")

    lines.append(t("strategy_list_hint", lang))
    return truncate_message("\n".join(lines))


def format_strategy_detail(
    strategy: TickerStrategy,
    *,
    display_text: str | None = None,
    lang: str = "en",
    is_developer: bool = False,
) -> str:
    """Render the full investment idea for one ticker."""
    body = (display_text if display_text is not None else strategy.strategy_text).strip()
    lines = [
        t("strategy_detail_header", lang, symbol=strategy.ticker),
        t(
            "strategy_holding_horizon",
            lang,
            horizon=_horizon_label(strategy.holding_horizon, lang),
        ),
        "",
        body,
    ]
    if is_developer:
        lines.extend(
            [
                "",
                t("strategy_developer_notes", lang),
                strategy.developer_reasoning,
                "",
                t(
                    "strategy_updated",
                    lang,
                    date=_format_user_date(strategy.updated_at),
                ),
            ]
        )
    lines.extend(["", t("advisory_footer", lang)])
    return truncate_message("\n".join(lines))


def format_strategy_announcement(
    ticker: str,
    shares: float,
    announcement_text: str,
    *,
    lang: str = "en",
) -> str:
    """Format the Telegram alert sent when a developer adds a new holding."""
    symbol = ticker.strip().upper()
    lines = [
        t("strategy_announcement_header", lang),
        t("strategy_announcement_added", lang, symbol=symbol, shares=shares),
        "",
        announcement_text.strip(),
        "",
        t("strategy_announcement_hint", lang, symbol=symbol),
        "",
        t("advisory_footer", lang),
    ]
    return truncate_message("\n".join(lines))


def format_sell_announcement(
    ticker: str,
    shares_sold: float,
    announcement_text: str,
    *,
    fully_sold: bool,
    lang: str = "en",
) -> str:
    """Format a sell announcement for ordinary users."""
    symbol = ticker.strip().upper()
    if fully_sold:
        detail = t("sell_announcement_sold_all", lang, symbol=symbol, shares=shares_sold)
    else:
        detail = t(
            "sell_announcement_sold_partial",
            lang,
            symbol=symbol,
            shares=shares_sold,
        )
    lines = [
        t("sell_announcement_header", lang),
        detail,
        "",
        announcement_text.strip(),
        "",
        t("advisory_footer", lang),
    ]
    return truncate_message("\n".join(lines))


def format_portfolio_correction_notification(
    *,
    action_type: Literal["sell", "add_ticker", "remove_ticker"],
    payload: dict[str, str | float | bool | None],
    lang: str = "en",
) -> str:
    """Format a correction after the developer undoes a portfolio notification."""
    symbol = str(payload.get("ticker", "")).strip().upper()
    if action_type == "sell":
        detail = t("portfolio_correction_sell", lang, symbol=symbol)
    elif action_type == "add_ticker":
        detail = t("portfolio_correction_add", lang, symbol=symbol)
    else:
        detail = t("portfolio_correction_remove", lang, symbol=symbol)
    lines = [
        t("portfolio_correction_header", lang),
        detail,
        "",
        t("advisory_footer", lang),
    ]
    return truncate_message("\n".join(lines))


def format_portfolio_change_notification(
    *,
    change: Literal["added_new", "added_shares", "removed"],
    symbol: str,
    shares: float = 0.0,
    lang: str = "en",
) -> str:
    """Format a portfolio holding change for ordinary users."""
    ticker = symbol.strip().upper()
    if change == "added_new":
        detail = t("portfolio_notify_added_new", lang, symbol=ticker, shares=shares)
    elif change == "added_shares":
        detail = t("portfolio_notify_added_shares", lang, symbol=ticker, shares=shares)
    else:
        detail = t("portfolio_notify_removed", lang, symbol=ticker)
    lines = [
        t("portfolio_notify_header", lang),
        detail,
        "",
        t("advisory_footer", lang),
    ]
    return truncate_message("\n".join(lines))


def format_strategy_update_notification(
    ticker: str,
    strategy_text: str,
    *,
    lang: str = "en",
) -> str:
    """Format a strategy update for ordinary users."""
    symbol = ticker.strip().upper()
    lines = [
        t("strategy_notify_header", lang),
        f"{symbol}:",
        "",
        strategy_text.strip(),
        "",
        t("strategy_announcement_hint", lang, symbol=symbol),
        "",
        t("advisory_footer", lang),
    ]
    return truncate_message("\n".join(lines))
