"""Scheduler setup and job registration."""

import logging
from dataclasses import dataclass

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from config.loader import ConfigurationBundle
from storage.repository import DataRepository

logger = logging.getLogger(__name__)


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


def build_scheduler(
    configuration: ConfigurationBundle,
    repository: DataRepository,
) -> AppScheduler:
    """Create a scheduler with placeholder jobs for future collectors."""
    scheduler = BlockingScheduler(timezone=configuration.app_config.timezone)

    def heartbeat() -> None:
        logger.debug(
            "Scheduler heartbeat (positions=%d)",
            len(configuration.portfolio.positions),
        )

    trigger = CronTrigger(
        hour=configuration.app_config.digest_hour,
        minute=configuration.app_config.digest_minute,
        timezone=configuration.app_config.timezone,
    )
    scheduler.add_job(
        heartbeat,
        trigger=trigger,
        id="heartbeat",
        replace_existing=True,
    )

    return AppScheduler(
        scheduler=scheduler,
        configuration=configuration,
        repository=repository,
    )
