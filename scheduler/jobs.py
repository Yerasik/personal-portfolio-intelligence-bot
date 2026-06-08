"""Scheduler setup and job registration.

Runs on a daemon thread alongside Telegram polling. Job intervals come from
data/config.json (market_fetch_interval_minutes, etc.).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Final

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from analysis.industries import build_news_focus_industries
from analysis.llm import LlmClient
from analysis.move_explainer import explain_price_move, recent_news_titles_for_ticker
from analysis.rules import AlertCandidate, RulesEngine
from analysis.summarizer import Summarizer
from collectors.base import CollectorContext
from collectors.market_data import MarketDataCollector
from collectors.news_data import NewsDataCollector
from config.loader import ConfigurationBundle
from config.settings import RuntimeSettings
from storage.models import AppConfig, BotState, NewsCache, PendingAlert
from storage.repository import DataRepository

from bot.notifier import TelegramNotifier, build_localized_daily_content

logger = logging.getLogger(__name__)

JOB_MARKET_FETCH: Final = "market_fetch"
JOB_NEWS_FETCH: Final = "news_fetch"
JOB_RULE_EVALUATION: Final = "rule_evaluation"
JOB_DAILY_SUMMARY: Final = "daily_summary"

_built_scheduler: AppScheduler | None = None
_scheduler_thread: threading.Thread | None = None
_scheduler_lock = threading.Lock()


@dataclass
class SchedulerServices:
    """Dependencies shared by scheduled jobs."""

    repository: DataRepository
    runtime: RuntimeSettings
    notifier: TelegramNotifier | None = None

    def get_notifier(self) -> TelegramNotifier:
        """Lazily create the Telegram notifier used for outbound alerts."""
        if self.notifier is None:
            self.notifier = TelegramNotifier(self.runtime)
        return self.notifier

    def load_app_config(self) -> AppConfig:
        """Reload config.json on each job run so interval/threshold edits apply."""
        return self.repository.load_config()

    def build_summarizer(self) -> Summarizer:
        """Construct rules + LLM stack for the daily summary job."""
        app_config = self.load_app_config()
        ticker_industries = self.repository.load_ticker_industries()
        rules = RulesEngine(
            app_config=app_config,
            ticker_to_industry=ticker_industries.ticker_to_industry,
        )
        llm = LlmClient(settings=self.runtime, app_config=app_config)
        return Summarizer(app_config=app_config, rules=rules, llm=llm)


@dataclass
class AppScheduler:
    """Owns the blocking APScheduler instance and registered jobs."""

    scheduler: BlockingScheduler
    services: SchedulerServices
    _started: bool = field(default=False, init=False)

    def start(self) -> None:
        """Start the scheduler; blocks until shutdown is requested."""
        if self._started or self.scheduler.running:
            logger.warning("Scheduler already running; skipping duplicate start")
            return

        self._started = True
        logger.info("Starting APScheduler")
        self.scheduler.start()

    def shutdown(self) -> None:
        """Stop APScheduler without blocking the main Telegram thread."""
        if not self.scheduler.running:
            return
        self.scheduler.shutdown(wait=False)
        self._started = False
        logger.info("APScheduler shut down")


def _run_job(job_id: str, action: Callable[[], None]) -> None:
    """Execute a scheduled job and log success or failure without raising."""
    logger.info("Job started: %s", job_id)
    try:
        action()
    except Exception:
        logger.exception("Job failed: %s", job_id)
    else:
        logger.info("Job succeeded: %s", job_id)


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
    )


_PRICE_MOVE_ALERT_TYPES: Final = ("price_drop", "price_rise")


def _enrich_price_move_alerts(
    services: SchedulerServices,
    alerts: list[AlertCandidate],
    state: BotState,
    news_cache: NewsCache,
    app_config: AppConfig,
) -> list[AlertCandidate]:
    """Attach best-effort LLM explanations to price-move alerts."""
    if not app_config.enable_llm_summaries:
        return alerts

    llm = LlmClient(settings=services.runtime, app_config=app_config)
    enriched: list[AlertCandidate] = []
    for alert in alerts:
        quote = state.latest_prices.get(alert.ticker) if alert.ticker else None
        if (
            alert.type in _PRICE_MOVE_ALERT_TYPES
            and alert.ticker
            and quote is not None
            and quote.change_pct is not None
        ):
            news = recent_news_titles_for_ticker(news_cache, alert.ticker)
            explanation = explain_price_move(
                llm,
                alert.ticker,
                quote.change_pct,
                "today",
                news,
                company_name=quote.company_name,
                sector=quote.sector,
            )
            alert = replace(alert, llm_explanation=explanation.to_message())
        enriched.append(alert)
    return enriched


def run_market_data_job(services: SchedulerServices) -> None:
    """Refresh market quotes for portfolio tickers."""
    app_config = services.load_app_config()
    portfolio = services.repository.load_portfolio()
    context = CollectorContext(
        repository=services.repository,
        app_config=app_config,
        portfolio=portfolio,
    )
    result = MarketDataCollector().run(context)
    logger.info(
        "Market data refresh finished (success=%s): %s",
        result.success,
        result.message,
    )
    if not result.success:
        raise RuntimeError(result.message)


def run_news_data_job(services: SchedulerServices) -> None:
    """Refresh RSS news cache."""
    app_config = services.load_app_config()
    portfolio = services.repository.load_portfolio()
    ticker_industries = services.repository.load_ticker_industries()
    focus_industries = build_news_focus_industries(
        app_config.focus_industries,
        portfolio,
        ticker_industries.ticker_to_industry,
    )
    context = CollectorContext(
        repository=services.repository,
        app_config=app_config,
        portfolio=portfolio,
        focus_industries=tuple(focus_industries),
    )
    logger.info(
        "News focus industries selected from config + portfolio: %s",
        focus_industries or "none",
    )
    result = NewsDataCollector().run(context)
    logger.info(
        "News refresh finished (success=%s): %s",
        result.success,
        result.message,
    )
    if not result.success:
        raise RuntimeError(result.message)


def run_rule_evaluation_job(services: SchedulerServices) -> None:
    """Evaluate rules, persist pending alerts, and deliver urgent Telegram alerts."""
    app_config = services.load_app_config()
    portfolio = services.repository.load_portfolio()
    state = services.repository.load_state()
    news_cache = services.repository.load_news_cache()

    ticker_industries = services.repository.load_ticker_industries()
    rules = RulesEngine(
        app_config=app_config,
        ticker_to_industry=ticker_industries.ticker_to_industry,
    )
    alerts = rules.evaluate(portfolio, state, news_cache)
    alerts = _enrich_price_move_alerts(services, alerts, state, news_cache, app_config)

    state.pending_alerts = [_alert_to_pending(alert) for alert in alerts]
    services.repository.save_state(state)

    logger.info("Rule evaluation finished with %d alert(s)", len(alerts))

    delivery = services.get_notifier().deliver_urgent_alerts(
        alerts,
        services.repository,
        app_config,
    )
    logger.info(
        "Telegram urgent alert delivery: sent=%d skipped=%d failed=%d",
        delivery.sent,
        delivery.skipped,
        delivery.failed,
    )


def run_daily_summary_job(services: SchedulerServices) -> None:
    """Build the daily digest and send it to Telegram."""
    app_config = services.load_app_config()
    if not app_config.enable_daily_summary:
        logger.info("Daily summary disabled in config.json")
        return

    portfolio = services.repository.load_portfolio()
    ticker_industries = services.repository.load_ticker_industries()
    state = services.repository.load_state()
    news_cache = services.repository.load_news_cache()
    summarizer = services.build_summarizer()
    alerts = summarizer.rules.evaluate(portfolio, state, news_cache)

    advisory_by_language: dict[str, object | None] = {}
    news_summary_by_language: dict[str, object | None] = {}
    company_names = {
        symbol: quote.company_name
        for symbol, quote in state.latest_prices.items()
        if quote.company_name
    }
    languages = {
        user.language for user in services.repository.load_users().users
    } or {"en"}

    if app_config.enable_llm_summaries:
        advisory_by_language, news_summary_by_language = build_localized_daily_content(
            llm=summarizer.llm,
            portfolio=portfolio,
            app_config=app_config,
            state=state,
            news_cache=news_cache,
            alerts=alerts,
            ticker_to_industry=ticker_industries.ticker_to_industry,
            company_names=company_names,
            languages=languages,
        )

    logger.info("Daily summary generated with %d alert(s)", len(alerts))

    sent = services.get_notifier().deliver_daily_summary(
        portfolio=portfolio,
        alerts=alerts,
        advisory_by_language=advisory_by_language,
        app_config=app_config,
        repository=services.repository,
        news_summary_by_language=news_summary_by_language,
    )
    if sent:
        state = services.repository.load_state()
        state.last_digest_at = datetime.now(tz=UTC)
        services.repository.save_state(state)
        logger.info("Daily summary sent to Telegram")
    else:
        logger.warning("Daily summary was not sent to Telegram")


def register_jobs(scheduler: BlockingScheduler, services: SchedulerServices) -> None:
    """Register all scheduled jobs using intervals from config.json."""
    app_config = services.load_app_config()
    timezone = app_config.timezone
    now = datetime.now(tz=UTC)

    scheduler.add_job(
        lambda: _run_job(JOB_MARKET_FETCH, lambda: run_market_data_job(services)),
        trigger=IntervalTrigger(minutes=app_config.market_fetch_interval_minutes),
        id=JOB_MARKET_FETCH,
        replace_existing=True,
        next_run_time=now,
    )

    scheduler.add_job(
        lambda: _run_job(JOB_NEWS_FETCH, lambda: run_news_data_job(services)),
        trigger=IntervalTrigger(minutes=app_config.news_fetch_interval_minutes),
        id=JOB_NEWS_FETCH,
        replace_existing=True,
        next_run_time=now,
    )

    scheduler.add_job(
        lambda: _run_job(JOB_RULE_EVALUATION, lambda: run_rule_evaluation_job(services)),
        trigger=IntervalTrigger(minutes=app_config.rule_evaluation_interval_minutes),
        id=JOB_RULE_EVALUATION,
        replace_existing=True,
        next_run_time=now,
    )

    if app_config.enable_daily_summary:
        scheduler.add_job(
            lambda: _run_job(JOB_DAILY_SUMMARY, lambda: run_daily_summary_job(services)),
            trigger=CronTrigger(
                hour=app_config.digest_hour,
                minute=app_config.digest_minute,
                timezone=timezone,
            ),
            id=JOB_DAILY_SUMMARY,
            replace_existing=True,
        )

    registered = [job.id for job in scheduler.get_jobs()]
    logger.info(
        "Registered scheduler jobs: %s (timezone=%s)",
        ", ".join(registered),
        timezone,
    )


def build_scheduler(
    configuration: ConfigurationBundle,
    repository: DataRepository,
) -> AppScheduler:
    """Create and configure the application scheduler."""
    global _built_scheduler

    with _scheduler_lock:
        if _built_scheduler is not None:
            logger.warning("Scheduler already built; returning existing instance")
            return _built_scheduler

        services = SchedulerServices(
            repository=repository,
            runtime=configuration.runtime,
            notifier=TelegramNotifier(configuration.runtime),
        )
        # A single worker serializes all jobs so concurrent load/modify/save
        # cycles cannot clobber each other's state.json updates. coalesce +
        # misfire_grace_time absorb the startup burst and any delayed runs.
        scheduler = BlockingScheduler(
            timezone=services.load_app_config().timezone,
            executors={"default": ThreadPoolExecutor(max_workers=1)},
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": 60,
            },
        )
        register_jobs(scheduler, services)

        _built_scheduler = AppScheduler(scheduler=scheduler, services=services)
        return _built_scheduler


def start_scheduler_background(app_scheduler: AppScheduler) -> threading.Thread:
    """Start the blocking scheduler on a daemon thread exactly once."""
    global _scheduler_thread

    with _scheduler_lock:
        if _scheduler_thread is not None and _scheduler_thread.is_alive():
            logger.warning("Scheduler thread already running; skipping duplicate startup")
            return _scheduler_thread

        _scheduler_thread = threading.Thread(
            target=app_scheduler.start,
            name="apscheduler",
            daemon=True,
        )
        _scheduler_thread.start()
        logger.info("Background scheduler thread started")
        return _scheduler_thread
