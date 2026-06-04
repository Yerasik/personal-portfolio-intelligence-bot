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
from config.startup import (
    StartupError,
    load_runtime_settings,
    run_startup_checks,
    validate_telegram_credentials,
)
from logging_setup import setup_logging
from scheduler.jobs import AppScheduler, build_scheduler, start_scheduler_background
from storage.repository import DataRepository

logger = logging.getLogger(__name__)


def _build_analysis_stack(configuration: ConfigurationBundle) -> Summarizer:
    rules = RulesEngine(app_config=configuration.app_config)
    llm = LlmClient(
        settings=configuration.runtime,
        app_config=configuration.app_config,
    )
    return Summarizer(
        app_config=configuration.app_config,
        rules=rules,
        llm=llm,
    )


def run() -> int:
    """Load configuration, validate startup state, and run the bot process."""
    try:
        runtime = load_runtime_settings()
        validate_telegram_credentials(runtime)
    except StartupError:
        return 1

    setup_logging(runtime.log_level, runtime.log_dir)

    try:
        configuration = load_configuration(runtime)
        run_startup_checks(configuration)
    except StartupError:
        return 1

    repository = DataRepository(configuration.paths)
    summarizer = _build_analysis_stack(configuration)
    digest_preview = summarizer.build_digest(
        configuration.portfolio,
        configuration.state,
        configuration.news_cache,
    )
    logger.info("Startup digest preview:\n%s", digest_preview)

    llm = LlmClient(
        settings=configuration.runtime,
        app_config=configuration.app_config,
    )
    bot_context = build_bot_context(configuration.runtime, repository, llm)
    app_scheduler = build_scheduler(configuration, repository)
    start_scheduler_background(app_scheduler)

    def handle_shutdown(signum: int, _frame: FrameType | None) -> None:
        logger.info("Received signal %s, shutting down", signum)
        app_scheduler.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    logger.info("Starting Telegram polling (single-process mode)")
    try:
        bot_context.application.run_polling(drop_pending_updates=True)
    finally:
        app_scheduler.shutdown()
        logger.info("Portfolio bot stopped cleanly")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
