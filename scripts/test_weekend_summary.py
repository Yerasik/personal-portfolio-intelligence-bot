#!/usr/bin/env python3
"""Smoke tests for weekend digest muting and Sunday evening rollup."""

from __future__ import annotations

import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.weekend_schedule import is_saturday, is_sunday, is_weekend
from analysis.weekend_summary import run_weekend_summary, should_skip_weekend_summary
from bot.formatter import format_weekend_summary
from config.settings import RuntimeSettings
from scheduler.jobs import (
    JOB_DAILY_SUMMARY,
    JOB_WEEKEND_SUMMARY,
    SchedulerServices,
    register_jobs,
    run_daily_summary_job,
)
from storage.models import (
    AppConfig,
    BotState,
    BotUser,
    BotUsers,
    MarketQuote,
    NewsCache,
    Portfolio,
    Position,
)
from storage.paths import resolve_data_paths
from storage.repository import DataRepository

from apscheduler.schedulers.blocking import BlockingScheduler


SATURDAY = datetime(2026, 7, 18, 8, 0, tzinfo=ZoneInfo("Asia/Hong_Kong")).astimezone(UTC)
SUNDAY = datetime(2026, 7, 19, 20, 0, tzinfo=ZoneInfo("Asia/Hong_Kong")).astimezone(UTC)
MONDAY = datetime(2026, 7, 20, 8, 0, tzinfo=ZoneInfo("Asia/Hong_Kong")).astimezone(UTC)


def test_weekend_detection() -> None:
    if not is_saturday("Asia/Hong_Kong", SATURDAY):
        raise AssertionError("expected Saturday")
    if not is_sunday("Asia/Hong_Kong", SUNDAY):
        raise AssertionError("expected Sunday")
    if not is_weekend("Asia/Hong_Kong", SATURDAY):
        raise AssertionError("Saturday should be weekend")
    if is_weekend("Asia/Hong_Kong", MONDAY):
        raise AssertionError("Monday should not be weekend")


def test_format_weekend_summary() -> None:
    portfolio = Portfolio(positions=[Position(ticker="AAPL", shares=1)])
    state = BotState(
        latest_prices={
            "AAPL": MarketQuote(
                ticker="AAPL",
                price=180.0,
                change_pct=1.0,
                volume=1,
                company_name="Apple Inc.",
                fetched_at=MONDAY,
            )
        }
    )
    text = format_weekend_summary(
        portfolio,
        [],
        None,
        AppConfig(),
        state=state,
        news_cache=NewsCache(),
        lang="en",
    )
    if "Weekend Portfolio Summary" not in text:
        raise AssertionError("weekend title missing")
    if "muted on Saturday" not in text:
        raise AssertionError("weekend note missing")


def test_daily_summary_muted_on_weekend() -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="weekend-mute-"))
    try:
        paths = resolve_data_paths(temp_dir)
        repository = DataRepository(paths)
        repository.save_config(
            AppConfig(
                enable_daily_summary=True,
                mute_weekend_digests=True,
                timezone="Asia/Hong_Kong",
            )
        )
        repository.save_portfolio(
            Portfolio(positions=[Position(ticker="AAPL", shares=1)])
        )
        repository.save_users(
            BotUsers(users=[BotUser(chat_id=1, language="en", role="ordinary")])
        )

        notifier = MagicMock()
        services = SchedulerServices(
            repository=repository,
            runtime=RuntimeSettings(
                telegram_bot_token="token",
                telegram_chat_id="1",
            ),
            notifier=notifier,
        )

        # Patch the name used by the daily summary job.
        import scheduler.jobs as jobs_module

        original = jobs_module.is_weekend
        jobs_module.is_weekend = lambda timezone, now=None: True  # type: ignore[assignment]
        try:
            run_daily_summary_job(services)
        finally:
            jobs_module.is_weekend = original  # type: ignore[assignment]

        if notifier.deliver_daily_summary.called:
            raise AssertionError("daily summary should not send on weekend")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_weekend_summary_job_registered() -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="weekend-job-"))
    try:
        paths = resolve_data_paths(temp_dir)
        repository = DataRepository(paths)
        repository.save_config(
            AppConfig(
                enable_daily_summary=True,
                enable_weekend_summary=True,
                mute_weekend_digests=True,
                enable_deep_digest=False,
                enable_change_briefing=False,
                enable_weekly_summary=False,
                enable_catalyst_reminders=False,
            )
        )
        services = SchedulerServices(
            repository=repository,
            runtime=RuntimeSettings(
                telegram_bot_token="token",
                telegram_chat_id="1",
            ),
            notifier=MagicMock(),
        )
        scheduler = BlockingScheduler(timezone="Asia/Hong_Kong")
        register_jobs(scheduler, services)
        job_ids = {job.id for job in scheduler.get_jobs()}
        if JOB_WEEKEND_SUMMARY not in job_ids:
            raise AssertionError("weekend_summary job missing")
        if JOB_DAILY_SUMMARY not in job_ids:
            raise AssertionError("daily_summary job missing")
        daily = scheduler.get_job(JOB_DAILY_SUMMARY)
        assert daily is not None
        day_field = None
        for field in getattr(daily.trigger, "fields", []):
            if getattr(field, "name", None) == "day_of_week":
                day_field = str(field)
                break
        if day_field is None or (
            "mon" not in day_field.lower() and "fri" not in day_field.lower()
        ):
            weekend = scheduler.get_job(JOB_WEEKEND_SUMMARY)
            assert weekend is not None
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_weekend_summary_dedupe_and_send() -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="weekend-send-"))
    try:
        paths = resolve_data_paths(temp_dir)
        repository = DataRepository(paths)
        repository.save_config(
            AppConfig(
                enable_weekend_summary=True,
                timezone="Asia/Hong_Kong",
                enable_llm_summaries=False,
            )
        )
        repository.save_portfolio(
            Portfolio(positions=[Position(ticker="AAPL", shares=2)])
        )
        repository.save_state(
            BotState(
                latest_prices={
                    "AAPL": MarketQuote(
                        ticker="AAPL",
                        price=190.0,
                        change_pct=0.5,
                        volume=1,
                        company_name="Apple Inc.",
                        fetched_at=SUNDAY,
                    )
                }
            )
        )
        repository.save_users(
            BotUsers(users=[BotUser(chat_id=42, language="en", role="ordinary")])
        )
        repository.save_news_cache(NewsCache())

        class FakeNotifier:
            def __init__(self) -> None:
                self.calls = 0

            def deliver_weekend_summary(self, **kwargs) -> bool:
                self.calls += 1
                return True

        notifier = FakeNotifier()
        llm = MagicMock()
        llm.is_configured = False

        sent = run_weekend_summary(
            repository,
            repository.load_config(),
            notifier,  # type: ignore[arg-type]
            llm,
            now=SUNDAY,
        )
        if not sent or notifier.calls != 1:
            raise AssertionError("weekend summary should send once")

        state = repository.load_state()
        if state.last_weekend_summary_at is None:
            raise AssertionError("last_weekend_summary_at should be set")
        if not should_skip_weekend_summary(
            state, now=SUNDAY, timezone="Asia/Hong_Kong"
        ):
            raise AssertionError("same-day weekend summary should be skipped")

        duplicate = run_weekend_summary(
            repository,
            repository.load_config(),
            notifier,  # type: ignore[arg-type]
            llm,
            now=SUNDAY,
        )
        if duplicate or notifier.calls != 1:
            raise AssertionError("duplicate weekend summary should be skipped")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def run_test() -> None:
    test_weekend_detection()
    test_format_weekend_summary()
    test_daily_summary_muted_on_weekend()
    test_weekend_summary_job_registered()
    test_weekend_summary_dedupe_and_send()
    print("Weekend summary checks passed.")


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
