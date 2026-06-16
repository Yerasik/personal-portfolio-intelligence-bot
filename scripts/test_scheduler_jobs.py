#!/usr/bin/env python3
"""Smoke test for scheduled job registration and execution."""

from __future__ import annotations

import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scheduler.jobs as jobs_module
from config.loader import ConfigurationBundle
from config.settings import RuntimeSettings
from scheduler.jobs import (
    JOB_AUTO_NEWS_DISCOVERY,
    JOB_DAILY_SUMMARY,
    JOB_MARKET_FETCH,
    JOB_NEWS_FETCH,
    JOB_RULE_EVALUATION,
    JOB_SENTIMENT_ANALYSIS,
    SchedulerServices,
    _run_job,
    build_scheduler,
    register_jobs,
    run_news_data_job,
    run_rule_evaluation_job,
)
from collectors.base import CollectorContext, CollectorResult
from storage.models import (
    AppConfig,
    BotState,
    MarketQuote,
    Portfolio,
    Position,
    TickerIndustryMap,
)
from storage.paths import resolve_data_paths
from storage.repository import DataRepository

NOW = datetime(2026, 6, 4, 12, 0, tzinfo=UTC)


def _reset_scheduler_singleton() -> None:
    jobs_module._built_scheduler = None
    jobs_module._scheduler_thread = None


def _configuration(repository: DataRepository, runtime: RuntimeSettings) -> ConfigurationBundle:
    return ConfigurationBundle(
        runtime=runtime,
        paths=repository.paths,
        app_config=repository.load_config(),
        portfolio=repository.load_portfolio(),
        state=repository.load_state(),
        news_cache=repository.load_news_cache(),
    )


def run_test() -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="scheduler-test-"))
    print(f"Using temp data dir: {temp_dir}")

    try:
        _reset_scheduler_singleton()
        paths = resolve_data_paths(temp_dir)
        repository = DataRepository(paths)
        repository.save_config(
            AppConfig(
                market_fetch_interval_minutes=30,
                news_fetch_interval_minutes=60,
                rule_evaluation_interval_minutes=45,
                enable_daily_summary=True,
            )
        )
        repository.save_portfolio(
            Portfolio(positions=[Position(ticker="AAPL", shares=1)])
        )
        state = BotState(
            latest_prices={
                "AAPL": MarketQuote(
                    ticker="AAPL",
                    price=180.0,
                    change_pct=-6.0,
                    volume=1000,
                    fetched_at=NOW,
                )
            }
        )
        repository.save_state(state)

        runtime = RuntimeSettings(
            telegram_bot_token="token",
            telegram_chat_id="12345",
        )
        configuration = _configuration(repository, runtime)

        scheduler_a = build_scheduler(configuration, repository)
        scheduler_b = build_scheduler(configuration, repository)
        if scheduler_a is not scheduler_b:
            raise AssertionError("build_scheduler should return a singleton instance")

        job_ids = {job.id for job in scheduler_a.scheduler.get_jobs()}
        expected = {
            JOB_MARKET_FETCH,
            JOB_NEWS_FETCH,
            JOB_AUTO_NEWS_DISCOVERY,
            JOB_RULE_EVALUATION,
            JOB_SENTIMENT_ANALYSIS,
            JOB_DAILY_SUMMARY,
        }
        if job_ids != expected:
            raise AssertionError(f"unexpected jobs registered: {job_ids}")

        def _boom() -> None:
            raise RuntimeError("boom")

        _run_job("test_failure", _boom)
        _run_job("test_success", lambda: None)

        services = SchedulerServices(repository=repository, runtime=runtime)
        run_rule_evaluation_job(services)
        updated_state = repository.load_state()
        if len(updated_state.pending_alerts) != 1:
            raise AssertionError("rule evaluation should persist one pending alert")

        captured_industries: tuple[str, ...] | None = None

        class RecordingNewsCollector:
            def run(self, context: CollectorContext) -> CollectorResult:
                nonlocal captured_industries
                captured_industries = context.focus_industries
                return CollectorResult(
                    name="news_data",
                    success=True,
                    message="captured",
                )

        original_news_collector = jobs_module.NewsDataCollector
        try:
            repository.save_config(AppConfig(focus_industries=["AI"]))
            repository.save_ticker_industries(
                TickerIndustryMap(
                    ticker_to_industry={
                        "AAPL": "Consumer Electronics",
                        "MSFT": "Software - Infrastructure",
                    }
                )
            )
            jobs_module.NewsDataCollector = RecordingNewsCollector
            run_news_data_job(services)
        finally:
            jobs_module.NewsDataCollector = original_news_collector

        if captured_industries != ("AI", "Consumer Electronics"):
            raise AssertionError(
                f"news job passed unexpected industries: {captured_industries}"
            )

        repository.save_config(AppConfig(enable_daily_summary=False))
        from apscheduler.schedulers.blocking import BlockingScheduler

        empty_scheduler = BlockingScheduler(timezone="UTC")
        register_jobs(empty_scheduler, services)
        job_ids_without_summary = {job.id for job in empty_scheduler.get_jobs()}
        if JOB_DAILY_SUMMARY in job_ids_without_summary:
            raise AssertionError("daily summary job should be omitted when disabled")

        print("Registered jobs:", sorted(job_ids))
        print("Pending alerts after rule evaluation:", len(updated_state.pending_alerts))
        print("Scheduler job checks passed.")
    finally:
        _reset_scheduler_singleton()
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
