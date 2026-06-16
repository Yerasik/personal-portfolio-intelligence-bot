"""Evaluate portfolio rules and push alerts to Telegram."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from analysis.llm import LlmClient
from analysis.rules import AlertCandidate, RulesEngine
from bot.notifier import AlertDeliveryResult, TelegramNotifier
from collectors.base import CollectorContext
from collectors.market_data import MarketDataCollector
from config.settings import RuntimeSettings
from storage.models import AppConfig, BotState, EvaluatedAlertRecord, PendingAlert
from storage.repository import DataRepository

logger = logging.getLogger(__name__)


def _alert_to_pending(alert: AlertCandidate) -> PendingAlert:
    """Convert a rules-engine candidate into the JSON shape stored in state.json."""
    return PendingAlert(
        id=alert.id,
        type=alert.type,
        severity=alert.urgency,
        message=f"{alert.title}: {alert.explanation}",
        created_at=alert.created_at,
        related_tickers=[alert.ticker] if alert.ticker else [],
        industry=alert.industry,
        llm_explanation=alert.llm_explanation,
        details=alert.details,
    )


def _record_evaluated_alerts(
    state: BotState,
    alerts: list[AlertCandidate],
    *,
    evaluated_at: datetime,
    suppression_hours: int,
) -> None:
    """Remember evaluated alert keys so warning/info alerts are not regenerated every run."""
    from datetime import timedelta

    for alert in alerts:
        state.last_evaluated_alerts.append(
            EvaluatedAlertRecord(
                alert_key=alert.alert_key,
                evaluated_at=evaluated_at,
            )
        )
    retention = timedelta(hours=max(suppression_hours * 4, 24))
    cutoff = evaluated_at - retention
    state.last_evaluated_alerts = [
        record for record in state.last_evaluated_alerts if record.evaluated_at >= cutoff
    ]


def evaluate_and_deliver_alerts(
    repository: DataRepository,
    runtime: RuntimeSettings,
    notifier: TelegramNotifier,
    *,
    llm: LlmClient | None = None,
    app_config: AppConfig | None = None,
) -> AlertDeliveryResult:
    """Run rules, persist pending alerts, and push warning/urgent alerts to all users."""
    config = app_config or repository.load_config()
    portfolio = repository.load_portfolio()
    state = repository.load_state()
    news_cache = repository.load_news_cache()
    ticker_industries = repository.load_ticker_industries()

    rules = RulesEngine(
        app_config=config,
        ticker_to_industry=ticker_industries.ticker_to_industry,
    )
    alerts = rules.evaluate(portfolio, state, news_cache)
    evaluated_at = datetime.now(tz=UTC)
    _record_evaluated_alerts(
        state,
        alerts,
        evaluated_at=evaluated_at,
        suppression_hours=config.alert_suppression_hours,
    )
    state.pending_alerts = [_alert_to_pending(alert) for alert in alerts]
    repository.save_state(state)

    logger.info("Alert evaluation finished with %d alert(s)", len(alerts))

    if llm is None:
        llm = LlmClient(settings=runtime, app_config=config)

    delivery = notifier.deliver_alerts(
        alerts,
        repository,
        config,
        llm=llm,
        state=state,
        news_cache=news_cache,
    )
    logger.info(
        "Telegram alert delivery: sent=%d skipped=%d failed=%d",
        delivery.sent,
        delivery.skipped,
        delivery.failed,
    )
    return delivery


def refresh_market_data_and_deliver_alerts(
    repository: DataRepository,
    runtime: RuntimeSettings,
    notifier: TelegramNotifier,
    *,
    llm: LlmClient | None = None,
) -> AlertDeliveryResult:
    """Fetch fresh quotes, then evaluate and deliver alerts immediately."""
    app_config = repository.load_config()
    portfolio = repository.load_portfolio()
    context = CollectorContext(
        repository=repository,
        app_config=app_config,
        portfolio=portfolio,
    )
    result = MarketDataCollector().run(context)
    logger.info(
        "Immediate market refresh finished (success=%s): %s",
        result.success,
        result.message,
    )
    if not result.success:
        raise RuntimeError(result.message)

    return evaluate_and_deliver_alerts(
        repository,
        runtime,
        notifier,
        llm=llm,
        app_config=app_config,
    )
