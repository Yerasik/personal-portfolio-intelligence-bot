"""Monday weekly portfolio summary with performance metrics and chart."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from analysis.performance_chart import render_performance_chart_png
from analysis.performance_metrics import compute_performance_metrics
from analysis.portfolio_valuation import portfolio_cash_hkd
from bot.formatter import format_weekly_summary
from bot.notifier import TelegramNotifier
from storage.models import AppConfig, BotState
from storage.repository import DataRepository

logger = logging.getLogger(__name__)


def _week_key(value: datetime, timezone: str) -> tuple[int, int]:
    """Return ISO (year, week) for deduplication in the app timezone."""
    local = value.astimezone(ZoneInfo(timezone))
    year, week, _ = local.isocalendar()
    return year, week


def should_skip_weekly_summary(
    state: BotState,
    *,
    now: datetime,
    timezone: str,
) -> bool:
    """Skip when a weekly summary was already sent this ISO week."""
    if state.last_weekly_summary_at is None:
        return False

    sent_at = state.last_weekly_summary_at
    if sent_at.tzinfo is None:
        sent_at = sent_at.replace(tzinfo=UTC)
    return _week_key(sent_at, timezone) == _week_key(now, timezone)


def run_weekly_summary(
    repository: DataRepository,
    app_config: AppConfig,
    notifier: TelegramNotifier,
    *,
    force: bool = False,
    now: datetime | None = None,
) -> bool:
    """Build and deliver the Monday weekly summary; return True when sent."""
    if not app_config.enable_weekly_summary:
        logger.info("Weekly summary disabled in config.json")
        return False

    evaluated_at = now or datetime.now(tz=UTC)
    state = repository.load_state()
    if not force and should_skip_weekly_summary(
        state,
        now=evaluated_at,
        timezone=app_config.timezone,
    ):
        logger.info("Weekly summary skipped: already sent this week")
        return False

    portfolio = repository.load_portfolio()
    performance_history = repository.load_performance_history()
    if not portfolio.positions and portfolio_cash_hkd(portfolio) <= 0:
        logger.info("Weekly summary skipped: empty portfolio")
        return False

    chart = render_performance_chart_png(
        performance_history,
        period="month",
        timezone=app_config.timezone,
    )
    metrics = compute_performance_metrics(performance_history)
    if metrics is None and chart is None:
        logger.info("Weekly summary skipped: no performance history yet")
        return False

    sent = notifier.deliver_weekly_summary(
        repository=repository,
        portfolio=portfolio,
        state=state,
        performance_history=performance_history,
        chart_png=chart,
    )
    if sent:
        state = repository.load_state()
        state.last_weekly_summary_at = evaluated_at
        repository.save_state(state)
        logger.info("Weekly summary delivered")
    else:
        logger.warning("Weekly summary was not delivered")
    return sent
