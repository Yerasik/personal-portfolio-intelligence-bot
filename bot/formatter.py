"""Message formatting helpers for Telegram delivery."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from collections.abc import Iterator

from analysis.llm import LlmAdvisoryResult
from analysis.move_explainer import PriceMoveExplanation
from analysis.news_summarizer import NewsGroupSummary, NewsSummary
from analysis.portfolio_valuation import (
    PositionValuation,
    PortfolioValuation,
    build_portfolio_valuation,
    infer_quote_currency,
)
from analysis.rules import AlertCandidate
from bot.i18n import t
from storage.models import (
    AppConfig,
    BotState,
    MarketQuote,
    NewsCache,
    PendingAlert,
    Portfolio,
    TickerStrategy,
)

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
    if alert.type in {"price_drop", "repeated_negative_news"} and alert.ticker:
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
    lang: str = "en",
) -> str:
    """Render a compact ticker-news block for the daily digest."""
    if news_summary is None or not news_summary.ticker_summaries:
        return ""

    lines = [t("daily_news_brief_title", lang), ""]
    for ticker, summary in news_summary.ticker_summaries.items():
        lines.append(f"{ticker}:")
        lines.append(summary)
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


def format_daily_summary(
    portfolio: Portfolio,
    alerts: list[AlertCandidate],
    advisory: LlmAdvisoryResult | None,
    app_config: AppConfig,
    news_summary: NewsSummary | None = None,
    *,
    state: BotState | None = None,
    lang: str = "en",
) -> str:
    """Format a concise daily summary for Telegram delivery."""
    _ = advisory, app_config
    lines = [
        t("daily_summary", lang),
        t(
            "holdings_alerts",
            lang,
            holdings=len(portfolio.positions),
            alerts=len(alerts),
        ),
    ]

    if state is not None and portfolio.positions:
        valuation = build_portfolio_valuation(portfolio, state)
        lines.append(
            t(
                "daily_portfolio_value_hkd",
                lang,
                value=valuation.total_market_value_hkd,
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

    lines.append("")

    if alerts:
        lines.append(t("alerts_header", lang))
        for alert in alerts[:3]:
            lines.append(_localized_alert_line(alert, lang))
        if len(alerts) > 3:
            lines.append(t("plus_more", lang, count=len(alerts) - 3))
        lines.append("")

    brief = format_daily_news_brief(news_summary, lang=lang)
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
    lang: str = "en",
    is_developer: bool = False,
) -> str:
    """Render portfolio holdings with latest market quotes."""
    if not portfolio.positions:
        key = "portfolio_empty_dev" if is_developer else "portfolio_empty"
        return t(key, lang)

    valuation = build_portfolio_valuation(portfolio, state)
    by_ticker = {item.ticker: item for item in valuation.positions}

    lines = [t("portfolio_header", lang, count=len(portfolio.positions)), ""]
    for position in portfolio.positions:
        symbol = position.ticker.strip().upper()
        lines.append(
            t("portfolio_shares", lang, symbol=symbol, shares=position.shares)
        )
        if position.cost_basis is not None:
            lines.append(
                t("portfolio_cost_basis", lang, value=position.cost_basis)
            )

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
            lines.append(
                t("portfolio_position_notes", lang, notes=position.notes)
            )
        lines.append("")

    if portfolio.notes:
        lines.extend([t("portfolio_notes_header", lang), portfolio.notes])

    lines.append("")
    _append_portfolio_totals_hkd(lines, valuation, lang)

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
    lang: str = "en",
    is_developer: bool = False,
) -> str:
    """Render rule alerts and optional LLM advisory output."""
    lines = [t("analyze_header", lang), ""]

    if alerts:
        lines.append(t("analyze_alerts_count", lang, count=len(alerts)))
        for alert in alerts:
            lines.append(_localized_alert_line(alert, lang))
            lines.append(f"  {_localized_alert_explanation(alert, lang)}")
        lines.append("")
    else:
        lines.extend([t("analyze_no_alerts", lang), ""])

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
    lines = [t("strategy_list_header", lang), ""]
    for position in portfolio.positions:
        symbol = position.ticker.strip().upper()
        strategy = strategies.get(symbol)
        if strategy is None:
            lines.append(t("strategy_list_missing", lang, symbol=symbol))
            continue
        preview = localized.get(symbol, strategy.strategy_text).replace("\n", " ").strip()
        if len(preview) > 120:
            preview = preview[:117].rstrip() + "..."
        lines.append(t("strategy_list_item", lang, symbol=symbol, preview=preview))

    lines.extend(["", t("strategy_list_hint", lang)])
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
