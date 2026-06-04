"""Scheduler setup and job registration."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from collectors.base import CollectorContext
from collectors.market_data import MarketDataCollector
from config.loader import ConfigurationBundle
from storage.repository import DataRepository

logger = logging.getLogger(__name__)

MARKET_FETCH_INTERVAL_MINUTES = 30


@dataclass
class AppScheduler:
    """Owns the blocking APScheduler instance and registered jobs."""

    scheduler: BlockingScheduler
    configuration: ConfigurationBundle
    repository: DataRepository

    def start(self) -> None:
        """Start the scheduler; blocks until shutdown is requested."""
        logger.info("Starting APScheduler")
        self.scheduler.start()

    def shutdown(self) -> None:
        self.scheduler.shutdown(wait=False)


def run_market_data_collector(
    configuration: ConfigurationBundle,
    repository: DataRepository,
) -> None:
    """Execute the market data collector with freshly loaded portfolio data."""
    portfolio = repository.load_portfolio()
    context = CollectorContext(
        repository=repository,
        app_config=configuration.app_config,
        portfolio=portfolio,
    )
    result = MarketDataCollector().run(context)
    logger.info(
        "Market data job finished (success=%s): %s",
        result.success,
        result.message,
    )


def build_scheduler(
    configuration: ConfigurationBundle,
    repository: DataRepository,
) -> AppScheduler:
    """Create a scheduler with market fetch and digest placeholder jobs."""
    scheduler = BlockingScheduler(timezone=configuration.app_config.timezone)

    def market_fetch_job() -> None:
        run_market_data_collector(configuration, repository)

    def heartbeat() -> None:
        logger.debug(
            "Scheduler heartbeat (positions=%d)",
            len(configuration.portfolio.positions),
        )

    scheduler.add_job(
        market_fetch_job,
        trigger=IntervalTrigger(minutes=MARKET_FETCH_INTERVAL_MINUTES),
        id="market_fetch",
        replace_existing=True,
        next_run_time=datetime.now(tz=UTC),
    )

    digest_trigger = CronTrigger(
        hour=configuration.app_config.digest_hour,
        minute=configuration.app_config.digest_minute,
        timezone=configuration.app_config.timezone,
    )
    scheduler.add_job(
        heartbeat,
        trigger=digest_trigger,
        id="heartbeat",
        replace_existing=True,
    )

    return AppScheduler(
        scheduler=scheduler,
        configuration=configuration,
        repository=repository,
    )
