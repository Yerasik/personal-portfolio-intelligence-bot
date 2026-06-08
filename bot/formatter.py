"""Message formatting helpers for Telegram delivery."""

from __future__ import annotations

from analysis.llm import LlmAdvisoryResult
from analysis.move_explainer import PriceMoveExplanation
from analysis.news_summarizer import NewsSummary
from analysis.rules import AlertCandidate
from bot.i18n import t
from storage.models import AppConfig, BotState, MarketQuote, NewsCache, PendingAlert, Portfolio

TELEGRAM_MESSAGE_LIMIT = 4096


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


def format_urgent_alert(alert: AlertCandidate, *, lang: str = "en") -> str:
    """Format an urgent alert for Telegram delivery."""
    target = alert.ticker or alert.industry or "portfolio"
    lines = [
        t("urgent_alert", lang),
        alert.title,
        f"{t('target', lang)}: {target}",
        alert.explanation,
    ]
    if alert.llm_explanation:
        lines.extend(["", alert.llm_explanation])
    lines.append(f"{t('suggested', lang)}: {_suggested_action(alert, lang)}.")
    return truncate_message("\n".join(lines))


def format_informational_alert(alert: AlertCandidate, *, lang: str = "en") -> str:
    """Format a non-urgent alert for Telegram delivery."""
    target = alert.ticker or alert.industry or "portfolio"
    lines = [
        f"{alert.urgency.upper()} update",
        alert.title,
        f"{t('target', lang)}: {target}",
        alert.explanation,
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


def format_news_summary(news_summary: NewsSummary, *, lang: str = "en") -> str:
    """Render on-demand /news_summary output."""
    lines = [t("news_summary_title", lang), ""]
    _append_news_summary_sections(lines, news_summary, lang=lang)
    lines.append(t("news_footer", lang))
    return truncate_message("\n".join(lines).strip())


def format_daily_summary(
    portfolio: Portfolio,
    alerts: list[AlertCandidate],
    advisory: LlmAdvisoryResult | None,
    app_config: AppConfig,
    news_summary: NewsSummary | None = None,
    *,
    lang: str = "en",
) -> str:
    """Format a concise daily summary for Telegram delivery."""
    lines = [
        t("daily_summary", lang),
        t(
            "holdings_alerts",
            lang,
            holdings=len(portfolio.positions),
            alerts=len(alerts),
        ),
        "",
    ]

    if alerts:
        lines.append(t("alerts_header", lang))
        for alert in alerts[:5]:
            target = alert.ticker or alert.industry or "n/a"
            lines.append(f"- [{alert.urgency}] {alert.title} ({target})")
        if len(alerts) > 5:
            lines.append(t("plus_more", lang, count=len(alerts) - 5))
        lines.append("")

    if app_config.enable_llm_summaries and advisory is not None:
        lines.extend([t("advisory", lang), advisory.summary])
        if advisory.suggested_actions:
            actions = "; ".join(advisory.suggested_actions[:3])
            lines.append(f"{t('actions', lang)} {actions}")
        lines.append("")

    if news_summary is not None:
        _append_news_summary_sections(lines, news_summary, lang=lang)

    lines.append(t("advisory_footer", lang))
    return truncate_message("\n".join(lines))


def format_start(*, lang: str = "en") -> str:
    """Welcome message for /start."""
    return (
        f"{t('welcome_title', lang)}\n\n"
        f"{t('welcome_body', lang)}\n\n"
        f"{t('welcome_menu', lang)}\n\n"
        f"{t('welcome_edit', lang)}"
    )


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
) -> str:
    """Render portfolio holdings with latest market quotes."""
    if not portfolio.positions:
        return t("portfolio_empty", lang)

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
        if quote is None or quote.price is None:
            lines.append(t("portfolio_price_unavailable", lang))
        else:
            change = (
                f"{quote.change_pct:+.2f}%"
                if quote.change_pct is not None
                else "n/a"
            )
            label = quote.company_name or symbol
            lines.append(
                t(
                    "portfolio_last_price",
                    lang,
                    price=quote.price,
                    change=change,
                )
            )
            lines.append(t("portfolio_company", lang, name=label))
            if quote.fetched_at:
                lines.append(
                    t(
                        "portfolio_quote_as_of",
                        lang,
                        timestamp=quote.fetched_at.isoformat(),
                    )
                )
        if position.notes:
            lines.append(
                t("portfolio_position_notes", lang, notes=position.notes)
            )
        lines.append("")

    if portfolio.notes:
        lines.extend([t("portfolio_notes_header", lang), portfolio.notes])

    if state.last_market_fetch_at:
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

    return truncate_message("\n".join(lines).strip())


def format_industries(
    focus_industries: list[str],
    news_cache: NewsCache,
    *,
    lang: str = "en",
) -> str:
    """Render focus industries with recent tagged news counts."""
    if not focus_industries:
        return t("industries_empty", lang)

    lines = [t("industries_header", lang), ""]
    for industry in focus_industries:
        label = industry.strip()
        if not label:
            continue
        count = sum(1 for item in news_cache.items if label in item.sector_tags)
        lines.append(t("industries_line", lang, label=label, count=count))

    lines.extend(["", t("industries_total", lang, count=len(news_cache.items))])
    if news_cache.updated_at:
        lines.append(
            t(
                "industries_updated",
                lang,
                timestamp=news_cache.updated_at.isoformat(),
            )
        )

    return truncate_message("\n".join(lines))


def format_analyze(
    alerts: list[AlertCandidate],
    advisory: LlmAdvisoryResult | None,
    app_config: AppConfig,
    *,
    lang: str = "en",
) -> str:
    """Render rule alerts and optional LLM advisory output."""
    lines = [t("analyze_header", lang), ""]

    if alerts:
        lines.append(t("analyze_alerts_count", lang, count=len(alerts)))
        for alert in alerts:
            target = alert.ticker or alert.industry or "portfolio"
            lines.append(
                f"- [{alert.urgency.upper()}] {alert.title} ({target})"
            )
            lines.append(f"  {alert.explanation}")
        lines.append("")
    else:
        lines.extend([t("analyze_no_alerts", lang), ""])

    if app_config.enable_llm_summaries:
        if advisory is None:
            lines.append(t("analyze_llm_empty", lang))
        else:
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
            if advisory.suggested_actions:
                actions = "; ".join(advisory.suggested_actions)
                lines.append(t("analyze_suggested", lang, actions=actions))
            if advisory.error:
                lines.append(t("analyze_llm_note", lang, note=advisory.error))
    else:
        lines.append(t("analyze_llm_disabled", lang))

    return truncate_message("\n".join(lines))


def format_ticker_analysis(
    ticker: str,
    quote: MarketQuote | None,
    window: str,
    explanation: PriceMoveExplanation | None,
    app_config: AppConfig,
    *,
    lang: str = "en",
) -> str:
    """Render on-demand /analyze output for a single ticker."""
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
    lines.append(
        t(
            "ticker_last_price",
            lang,
            price=quote.price,
            change=change,
            window=window,
        )
    )
    if quote.sector:
        lines.append(t("ticker_sector", lang, sector=quote.sector))
    lines.append("")

    if not app_config.enable_llm_summaries:
        lines.append(t("ticker_llm_disabled", lang))
    elif explanation is None:
        lines.append(t("ticker_llm_empty", lang))
    else:
        lines.append(explanation.to_message())

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
    )
    if alert.severity == "urgent":
        return format_urgent_alert(candidate, lang=lang)
    return format_informational_alert(candidate, lang=lang)
