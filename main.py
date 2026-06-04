"""Application entrypoint for the portfolio intelligence bot."""

from __future__ import annotations

import logging
import signal
import sys
from types import FrameType

from analysis.llm import LlmClient
from analysis.rules import RulesEngine
from analysis.summarizer import Summarizer
from bot.app import build_bot_context
from config.loader import ConfigurationBundle, load_configuration
from logging_setup import setup_logging
from scheduler.jobs import AppScheduler, build_scheduler
from storage.repository import DataRepository

logger = logging.getLogger(__name__)


def _log_startup_summary(configuration: ConfigurationBundle) -> None:
    portfolio = configuration.portfolio
    app_config = configuration.app_config
    runtime = configuration.runtime

    logger.info("Portfolio bot skeleton starting")
    logger.info("Data directory: %s", configuration.paths.root)
    logger.info("Timezone: %s", app_config.timezone)
    logger.info("Positions loaded: %d", len(portfolio.positions))
    logger.info("Focus industries: %d", len(app_config.focus_industries))
    logger.info("Cached news items: %d", len(configuration.news_cache.items))
    logger.info("Ollama endpoint: %s", runtime.ollama_base_url)
    logger.info("Telegram chat id configured: %s", bool(runtime.telegram_chat_id))


def _build_analysis_stack(configuration: ConfigurationBundle) -> Summarizer:
    rules = RulesEngine(app_config=configuration.app_config)
    llm = LlmClient(settings=configuration.runtime)
    return Summarizer(
        app_config=configuration.app_config,
        rules=rules,
        llm=llm,
    )


def run() -> int:
    """Load configuration, wire modules, and start the blocking scheduler."""
    configuration = load_configuration()
    setup_logging(configuration.runtime.log_level, configuration.runtime.log_dir)
    _log_startup_summary(configuration)

    repository = DataRepository(configuration.paths)
    summarizer = _build_analysis_stack(configuration)
    digest_preview = summarizer.build_digest(
        configuration.portfolio,
        configuration.state,
        configuration.news_cache,
    )
    logger.info("Digest preview:\n%s", digest_preview)

    bot_context = build_bot_context(configuration.runtime, repository)
    logger.info("Telegram application initialized (handlers not registered)")

    app_scheduler = build_scheduler(configuration, repository)

    def handle_shutdown(signum: int, _frame: FrameType | None) -> None:
        logger.info("Received signal %s, shutting down", signum)
        app_scheduler.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    _ = bot_context
    app_scheduler.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
