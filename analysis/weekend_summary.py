"""Sunday evening weekend portfolio rollup."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from analysis.llm import LlmClient
from analysis.performance_chart import render_performance_chart_png
from analysis.rules import RulesEngine
from analysis.weekend_schedule import is_sunday, same_local_date
from bot.notifier import TelegramNotifier, build_localized_daily_content
from storage.models import AppConfig, BotState
from storage.repository import DataRepository

logger = logging.getLogger(__name__)


def should_skip_weekend_summary(
    state: BotState,
    *,
    now: datetime,
    timezone: str,
) -> bool:
    """Skip when a weekend summary was already sent today."""
    if state.last_weekend_summary_at is None:
        return False
    return same_local_date(
        state.last_weekend_summary_at,
        now,
        timezone=timezone,
    )


def run_weekend_summary(
    repository: DataRepository,
    app_config: AppConfig,
    notifier: TelegramNotifier,
    llm: LlmClient,
    *,
    force: bool = False,
    now: datetime | None = None,
) -> bool:
    """Build and deliver the Sunday evening weekend rollup; return True when sent."""
    if not app_config.enable_weekend_summary:
        logger.info("Weekend summary disabled in config.json")
        return False

    evaluated_at = now or datetime.now(tz=UTC)
    if not force and not is_sunday(app_config.timezone, evaluated_at):
        logger.info("Weekend summary skipped: not Sunday in %s", app_config.timezone)
        return False

    state = repository.load_state()
    if not force and should_skip_weekend_summary(
        state,
        now=evaluated_at,
        timezone=app_config.timezone,
    ):
        logger.info("Weekend summary skipped: already sent today")
        return False

    portfolio = repository.load_portfolio()
    if not portfolio.positions:
        logger.info("Weekend summary skipped: empty portfolio")
        return False

    ticker_industries = repository.load_ticker_industries()
    news_cache = repository.load_news_cache()
    rules = RulesEngine(
        app_config=app_config,
        ticker_to_industry=ticker_industries.ticker_to_industry,
    )
    alerts = rules.evaluate(portfolio, state, news_cache)

    company_names = {
        symbol: quote.company_name
        for symbol, quote in state.latest_prices.items()
        if quote.company_name
    }
    languages = {user.language for user in repository.load_users().users} or {"en"}
    advisory_by_language, news_summary_by_language = build_localized_daily_content(
        llm=llm,
        portfolio=portfolio,
        app_config=app_config,
        state=state,
        news_cache=news_cache,
        alerts=alerts,
        ticker_to_industry=ticker_industries.ticker_to_industry,
        company_names=company_names,
        languages=languages,
    )

    performance_history = repository.load_performance_history()
    chart_png = None
    if len(performance_history.snapshots) >= 2:
        chart_png = render_performance_chart_png(
            performance_history,
            period="week",
            timezone=app_config.timezone,
        )

    sent = notifier.deliver_weekend_summary(
        portfolio=portfolio,
        alerts=alerts,
        advisory_by_language=advisory_by_language,
        app_config=app_config,
        repository=repository,
        news_summary_by_language=news_summary_by_language,
        chart_png=chart_png,
    )
    if sent:
        state = repository.load_state()
        state.last_weekend_summary_at = evaluated_at
        repository.save_state(state)
        logger.info("Weekend summary delivered")
    else:
        logger.warning("Weekend summary was not delivered")
    return sent
