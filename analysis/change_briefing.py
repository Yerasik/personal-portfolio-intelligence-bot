"""What changed since yesterday — concise portfolio change briefing."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from analysis.llm import LlmAdvisoryResult, LlmClient, build_fallback_advisory
from analysis.portfolio_risk import PortfolioRiskAssessment, estimate_portfolio_risk
from analysis.rules import AlertCandidate, RulesEngine
from bot.notifier import TelegramNotifier
from collectors.market_data import portfolio_tickers
from storage.models import (
    AppConfig,
    BotState,
    NewsCache,
    PerformanceHistory,
    Portfolio,
    PortfolioPerformanceSnapshot,
    SignalsFile,
    TickerStrategy,
)
from storage.portfolio_ops import normalize_ticker
from storage.repository import DataRepository

logger = logging.getLogger(__name__)

_LOOKBACK = timedelta(hours=24)
_SENTIMENT_BREAK_THRESHOLD = -0.25
_MAX_DRIVERS = 5
_MAX_QUEUE = 8


@dataclass(frozen=True)
class PnLDriver:
    """Per-ticker contribution to portfolio value change."""

    ticker: str
    value_delta_hkd: float
    price_change_pct: float | None
    contribution_pct: float


@dataclass(frozen=True)
class ChangeBriefingContent:
    """Structured inputs for the change briefing formatter."""

    portfolio_daily_pnl_pct: float | None
    portfolio_value_delta_hkd: float | None
    pl_drivers: list[PnLDriver] = field(default_factory=list)
    new_risks: list[AlertCandidate] = field(default_factory=list)
    thesis_breaks: list[str] = field(default_factory=list)
    review_queue: list[str] = field(default_factory=list)
    risk_assessment: PortfolioRiskAssessment | None = None
    risk_score_delta: float | None = None
    llm_summary: str = ""


def _normalize_ts(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _snapshot_at_or_before(
    snapshots: list[PortfolioPerformanceSnapshot],
    target: datetime,
) -> PortfolioPerformanceSnapshot | None:
    """Return the latest snapshot at or before ``target``."""
    normalized_target = _normalize_ts(target)
    prior: PortfolioPerformanceSnapshot | None = None
    for item in sorted(snapshots, key=lambda row: _normalize_ts(row.timestamp)):
        if _normalize_ts(item.timestamp) <= normalized_target:
            prior = item
        else:
            break
    return prior


def compute_pl_drivers(
    history: PerformanceHistory,
    state: BotState,
    *,
    lookback: timedelta = _LOOKBACK,
) -> tuple[float | None, float | None, list[PnLDriver]]:
    """Rank tickers by HKD value delta vs ~24h ago."""
    if not history.snapshots:
        return None, None, []

    ordered = sorted(history.snapshots, key=lambda row: _normalize_ts(row.timestamp))
    latest = ordered[-1]
    prior = _snapshot_at_or_before(ordered, _normalize_ts(latest.timestamp) - lookback)
    if prior is None:
        prior = ordered[0]
    if prior is latest and len(ordered) < 2:
        return latest.daily_pnl_pct, None, []

    portfolio_delta = latest.total_value - prior.total_value
    daily_pnl = latest.daily_pnl_pct

    tickers = set(latest.positions) | set(prior.positions)
    drivers: list[PnLDriver] = []
    for ticker in tickers:
        latest_point = latest.positions.get(ticker)
        prior_point = prior.positions.get(ticker)
        latest_value = latest_point.value if latest_point is not None else 0.0
        prior_value = prior_point.value if prior_point is not None else 0.0
        delta = latest_value - prior_value
        if abs(delta) < 0.01:
            continue
        quote = state.latest_prices.get(ticker)
        price_pct = quote.change_pct if quote is not None else None
        contribution = (
            (delta / portfolio_delta) * 100.0 if abs(portfolio_delta) > 0.01 else 0.0
        )
        drivers.append(
            PnLDriver(
                ticker=ticker,
                value_delta_hkd=delta,
                price_change_pct=price_pct,
                contribution_pct=contribution,
            )
        )

    drivers.sort(key=lambda item: abs(item.value_delta_hkd), reverse=True)
    return daily_pnl, portfolio_delta, drivers[:_MAX_DRIVERS]


def filter_new_risks(
    alerts: list[AlertCandidate],
    prior_alert_keys: set[str],
) -> list[AlertCandidate]:
    """Return warning/urgent alerts not present at the last briefing."""
    fresh: list[AlertCandidate] = []
    for alert in alerts:
        if alert.urgency not in {"warning", "urgent"}:
            continue
        if alert.alert_key in prior_alert_keys:
            continue
        fresh.append(alert)
    return fresh


def detect_thesis_breaks(
    portfolio: Portfolio,
    strategies: dict[str, TickerStrategy],
    state: BotState,
    signals: SignalsFile,
    alerts: list[AlertCandidate],
    app_config: AppConfig,
) -> list[str]:
    """Flag holdings where price, news, or rules contradict the stored thesis."""
    breaks: list[str] = []
    alert_by_ticker: dict[str, list[AlertCandidate]] = {}
    for alert in alerts:
        if alert.ticker:
            alert_by_ticker.setdefault(alert.ticker, []).append(alert)

    for symbol in portfolio_tickers(portfolio):
        strategy = strategies.get(symbol)
        if strategy is None:
            continue

        reasons: list[str] = []
        quote = state.latest_prices.get(symbol)
        if quote is not None and quote.change_pct is not None:
            if quote.change_pct <= -app_config.alert_price_change_pct:
                reasons.append(
                    f"price {quote.change_pct:+.1f}% (threshold {app_config.alert_price_change_pct:g}%)"
                )

        sentiment = signals.sentiment.get(symbol)
        if sentiment is not None and sentiment.score <= _SENTIMENT_BREAK_THRESHOLD:
            reasons.append(f"negative news sentiment ({sentiment.score:+.2f})")

        for alert in alert_by_ticker.get(symbol, []):
            if alert.type in {
                "price_drop",
                "repeated_negative_news",
                "rsi_alert",
                "macd_crossover",
            }:
                reasons.append(alert.title)

        memo = signals.pros_cons.get(symbol)
        if memo is not None and memo.memo:
            lowered = memo.memo.lower()
            if any(
                token in lowered
                for token in ("thesis challenged", "downside risk", "bearish", "headwind")
            ):
                reasons.append("pros/cons memo flags pressure")

        if not reasons:
            continue

        unique = list(dict.fromkeys(reasons))[:3]
        horizon = strategy.holding_horizon
        breaks.append(f"{symbol} ({horizon}): {'; '.join(unique)}")

    return breaks


def build_review_queue(
    alerts: list[AlertCandidate],
    advisory: LlmAdvisoryResult | None,
    *,
    lang: str = "en",
) -> list[str]:
    """Merge rule-based actions with LLM suggested actions."""
    from bot.formatter import _suggested_action

    queue: list[str] = []
    for alert in alerts:
        queue.append(_suggested_action(alert, lang))
    if advisory is not None:
        queue.extend(advisory.suggested_actions)
    return list(dict.fromkeys(item for item in queue if item.strip()))[:_MAX_QUEUE]


def _optional_llm_summary(
    llm: LlmClient,
    content: ChangeBriefingContent,
    portfolio: Portfolio,
    *,
    language: str,
    enabled: bool,
) -> str:
    """One short LLM paragraph tying the briefing sections together."""
    if not enabled or not getattr(llm, "is_configured", False):
        return ""

    from bot.i18n import llm_language_clause

    drivers = ", ".join(
        f"{item.ticker} {item.value_delta_hkd:+,.0f} HKD"
        for item in content.pl_drivers[:3]
    ) or "none"
    risks = "; ".join(alert.title for alert in content.new_risks[:3]) or "none"
    breaks = "; ".join(content.thesis_breaks[:3]) or "none"
    queue = "; ".join(content.review_queue[:4]) or "none"

    prompt = (
        "You are a cautious portfolio assistant. Write ONE concise paragraph (max 4 sentences) "
        "summarizing what changed since yesterday for the holder. Advisory only; no trades.\n\n"
        f"P/L drivers: {drivers}\n"
        f"New risks: {risks}\n"
        f"Thesis pressure: {breaks}\n"
        f"Review queue: {queue}\n\n"
        f"{llm_language_clause(language)}"
    )
    try:
        return llm.generate(prompt).strip()[:700]
    except Exception as exc:
        logger.warning("Change briefing LLM summary failed: %s", exc)
        return ""


def assemble_change_briefing(
    repository: DataRepository,
    llm: LlmClient,
    *,
    language: str = "en",
    now: datetime | None = None,
) -> ChangeBriefingContent:
    """Build structured briefing content from current portfolio data."""
    evaluated_at = now or datetime.now(tz=UTC)
    app_config = repository.load_config()
    portfolio = repository.load_portfolio()
    state = repository.load_state()
    news_cache = repository.load_news_cache()
    signals = repository.load_signals()
    history = repository.load_performance_history()
    ticker_industries = repository.load_ticker_industries()
    strategies = repository.load_ticker_strategies().by_ticker

    rules = RulesEngine(
        app_config=app_config,
        ticker_to_industry=ticker_industries.ticker_to_industry,
    )
    alerts = rules.evaluate(portfolio, state, news_cache, now=evaluated_at)
    visible_alerts = [
        alert
        for alert in alerts
        if alert.urgency in {"warning", "urgent"}
        or alert.type in {"price_drop", "price_rise", "repeated_negative_news", "sector_attention"}
    ]

    prior_keys = set(state.change_brief_alert_keys)
    new_risks = filter_new_risks(visible_alerts, prior_keys)

    daily_pnl, value_delta, drivers = compute_pl_drivers(history, state)
    thesis_breaks = detect_thesis_breaks(
        portfolio,
        strategies,
        state,
        signals,
        visible_alerts,
        app_config,
    )

    risk = estimate_portfolio_risk(
        portfolio,
        state,
        signals,
        visible_alerts,
        app_config,
    )
    risk_delta: float | None = None
    if state.change_brief_risk_score is not None:
        risk_delta = risk.score - state.change_brief_risk_score

    advisory: LlmAdvisoryResult | None = None
    if app_config.enable_llm_summaries:
        advisory = llm.synthesize_advisory(
            portfolio,
            app_config,
            state,
            news_cache,
            visible_alerts,
            ticker_to_industry=ticker_industries.ticker_to_industry,
            language=language,
        )
    else:
        advisory = build_fallback_advisory(visible_alerts, portfolio)

    review_queue = build_review_queue(new_risks or visible_alerts[:3], advisory, lang=language)

    content = ChangeBriefingContent(
        portfolio_daily_pnl_pct=daily_pnl,
        portfolio_value_delta_hkd=value_delta,
        pl_drivers=drivers,
        new_risks=new_risks,
        thesis_breaks=thesis_breaks,
        review_queue=review_queue,
        risk_assessment=risk,
        risk_score_delta=risk_delta,
    )
    llm_summary = _optional_llm_summary(
        llm,
        content,
        portfolio,
        language=language,
        enabled=app_config.enable_llm_summaries,
    )
    from dataclasses import replace

    return replace(content, llm_summary=llm_summary)


def _same_local_day(left: datetime, right: datetime, timezone: str) -> bool:
    tz = ZoneInfo(timezone)
    return left.astimezone(tz).date() == right.astimezone(tz).date()


def should_skip_change_briefing(
    state: BotState,
    *,
    now: datetime,
    timezone: str,
) -> bool:
    """Skip when a change briefing was already sent today (app timezone)."""
    if state.last_change_brief_at is None:
        return False
    sent_at = _normalize_ts(state.last_change_brief_at)
    return _same_local_day(sent_at, _normalize_ts(now), timezone)


def record_change_briefing_delivery(
    repository: DataRepository,
    *,
    alerts: list[AlertCandidate],
    risk_score: float,
    sent_at: datetime,
) -> None:
    """Persist dedup markers after a successful briefing delivery."""
    state = repository.load_state()
    repository.save_state(
        state.model_copy(
            update={
                "last_change_brief_at": sent_at,
                "change_brief_alert_keys": [alert.alert_key for alert in alerts],
                "change_brief_risk_score": risk_score,
            }
        )
    )


def build_localized_change_briefings(
    repository: DataRepository,
    llm: LlmClient,
    *,
    now: datetime | None = None,
) -> dict[str, str]:
    """Build per-language briefing text for all configured user languages."""
    users = repository.load_users().users
    languages = {user.language for user in users} or {"en"}
    messages: dict[str, str] = {}
    for language in languages:
        content = assemble_change_briefing(repository, llm, language=language, now=now)
        from bot.formatter import format_change_briefing

        messages[language] = format_change_briefing(content, lang=language)
    return messages


def run_change_briefing(
    repository: DataRepository,
    app_config: AppConfig,
    notifier: TelegramNotifier,
    llm: LlmClient,
    *,
    force: bool = False,
    now: datetime | None = None,
) -> bool:
    """Build and deliver the daily change briefing; return True when sent."""
    if not app_config.enable_change_briefing:
        logger.info("Change briefing disabled in config.json")
        return False

    evaluated_at = now or datetime.now(tz=UTC)
    state = repository.load_state()
    if not force and should_skip_change_briefing(
        state,
        now=evaluated_at,
        timezone=app_config.timezone,
    ):
        logger.info("Change briefing skipped: already sent today")
        return False

    portfolio = repository.load_portfolio()
    if not portfolio.positions:
        logger.info("Change briefing skipped: empty portfolio")
        return False

    messages = build_localized_change_briefings(repository, llm, now=evaluated_at)
    sent = notifier.deliver_change_briefing(repository, messages)
    if not sent:
        logger.warning("Change briefing was not delivered")
        return False

    ticker_industries = repository.load_ticker_industries()
    rules = RulesEngine(
        app_config=app_config,
        ticker_to_industry=ticker_industries.ticker_to_industry,
    )
    news_cache = repository.load_news_cache()
    alerts = rules.evaluate(portfolio, repository.load_state(), news_cache, now=evaluated_at)
    content = assemble_change_briefing(repository, llm, language="en", now=evaluated_at)
    risk_score = content.risk_assessment.score if content.risk_assessment is not None else 0.0
    record_change_briefing_delivery(
        repository,
        alerts=alerts,
        risk_score=risk_score,
        sent_at=evaluated_at,
    )
    logger.info("Change briefing delivered")
    return True
