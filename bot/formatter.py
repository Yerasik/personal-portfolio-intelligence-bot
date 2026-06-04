"""Message formatting helpers for Telegram delivery."""

from __future__ import annotations

from analysis.llm import LlmAdvisoryResult
from analysis.rules import AlertCandidate
from storage.models import AppConfig, BotState, NewsCache, PendingAlert, Portfolio

TELEGRAM_MESSAGE_LIMIT = 4096


def truncate_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> str:
    """Trim long messages to fit Telegram limits."""
    if len(text) <= limit:
        return text
    suffix = "\n\n(message truncated)"
    return text[: limit - len(suffix)] + suffix


def format_start() -> str:
    """Welcome message for /start."""
    return (
        "Portfolio Intelligence Bot\n\n"
        "This bot monitors your portfolio, news, and rule-based alerts. "
        "It provides advisory guidance only and does not execute trades.\n\n"
        "Use /help to see available commands."
    )


def format_help() -> str:
    """Help text for /help."""
    return (
        "Available commands:\n\n"
        "/start — welcome message\n"
        "/help — show this help\n"
        "/portfolio — holdings and latest prices\n"
        "/industries — focus industries and recent news counts\n"
        "/analyze — run rules and optional LLM advisory summary"
    )


def format_portfolio(portfolio: Portfolio, state: BotState) -> str:
    """Render portfolio holdings with latest market quotes."""
    if not portfolio.positions:
        return "Portfolio is empty. Add positions to portfolio.json."

    lines = [f"Portfolio ({len(portfolio.positions)} position(s))", ""]
    for position in portfolio.positions:
        symbol = position.ticker.strip().upper()
        lines.append(f"{symbol} — {position.shares:g} shares")
        if position.cost_basis is not None:
            lines.append(f"  Cost basis: {position.cost_basis:.2f}")

        quote = state.latest_prices.get(symbol)
        if quote is None or quote.price is None:
            lines.append("  Price: unavailable")
        else:
            change = (
                f"{quote.change_pct:+.2f}%"
                if quote.change_pct is not None
                else "change n/a"
            )
            label = quote.company_name or symbol
            lines.append(f"  Last price: {quote.price:.2f} ({change})")
            lines.append(f"  Company: {label}")
            if quote.fetched_at:
                lines.append(f"  Quote as of: {quote.fetched_at.isoformat()}")
        if position.notes:
            lines.append(f"  Notes: {position.notes}")
        lines.append("")

    if portfolio.notes:
        lines.extend(["Portfolio notes:", portfolio.notes])

    if state.last_market_fetch_at:
        lines.extend(["", f"Last market fetch: {state.last_market_fetch_at.isoformat()}"])

    return truncate_message("\n".join(lines).strip())


def format_industries(app_config: AppConfig, news_cache: NewsCache) -> str:
    """Render focus industries with recent tagged news counts."""
    if not app_config.focus_industries:
        return (
            "No focus industries configured.\n"
            "Add entries to focus_industries in config.json."
        )

    lines = ["Focus industries", ""]
    for industry in app_config.focus_industries:
        label = industry.strip()
        if not label:
            continue
        count = sum(1 for item in news_cache.items if label in item.sector_tags)
        lines.append(f"- {label}: {count} cached article(s)")

    lines.extend(
        [
            "",
            f"Total cached news items: {len(news_cache.items)}",
        ]
    )
    if news_cache.updated_at:
        lines.append(f"News cache updated: {news_cache.updated_at.isoformat()}")

    return truncate_message("\n".join(lines))


def format_analyze(
    alerts: list[AlertCandidate],
    advisory: LlmAdvisoryResult | None,
    app_config: AppConfig,
) -> str:
    """Render rule alerts and optional LLM advisory output."""
    lines = ["Portfolio analysis", ""]

    if alerts:
        lines.append(f"Rule alerts ({len(alerts)}):")
        for alert in alerts:
            target = alert.ticker or alert.industry or "portfolio"
            lines.append(
                f"- [{alert.urgency.upper()}] {alert.title} ({target})"
            )
            lines.append(f"  {alert.explanation}")
        lines.append("")
    else:
        lines.extend(["Rule alerts: none triggered.", ""])

    if app_config.enable_llm_summaries:
        if advisory is None:
            lines.append("LLM advisory: enabled but no result returned.")
        else:
            lines.extend(
                [
                    f"LLM advisory ({advisory.source}, {advisory.urgency}):",
                    advisory.summary,
                ]
            )
            if advisory.suggested_actions:
                actions = "; ".join(advisory.suggested_actions)
                lines.append(f"Suggested actions: {actions}")
            if advisory.error:
                lines.append(f"LLM note: {advisory.error}")
    else:
        lines.append("LLM advisory: disabled (set enable_llm_summaries in config.json).")

    return truncate_message("\n".join(lines))


def format_alert(alert: PendingAlert) -> str:
    """Render a pending alert as a Telegram-friendly message."""
    tickers = ", ".join(alert.related_tickers) if alert.related_tickers else "n/a"
    return truncate_message(
        f"[{alert.severity.upper()}] {alert.message}\nTickers: {tickers}"
    )
