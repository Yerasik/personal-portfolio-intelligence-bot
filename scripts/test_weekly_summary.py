#!/usr/bin/env python3
"""Smoke tests for the Monday weekly summary job."""

from __future__ import annotations

import shutil
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.weekly_summary import run_weekly_summary, should_skip_weekly_summary
from bot.formatter import format_weekly_summary
from storage.models import (
    AppConfig,
    BotState,
    BotUser,
    BotUsers,
    PerformanceHistory,
    Portfolio,
    PortfolioPerformanceSnapshot,
    Position,
    PositionPerformancePoint,
)
from storage.paths import resolve_data_paths
from storage.repository import DataRepository


class RecordingNotifier:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []
        self.photos: list[int] = []

    @property
    def is_configured(self) -> bool:
        return True

    def deliver_weekly_summary(self, **kwargs) -> bool:
        repository = kwargs["repository"]
        for user in repository.load_users().users:
            self.calls.append(("weekly", user.chat_id))
            if kwargs.get("chart_png") is not None:
                self.photos.append(user.chat_id)
        return True


def run_test() -> None:
    now = datetime(2026, 6, 22, 8, 0, tzinfo=UTC)  # Monday
    state = BotState(last_weekly_summary_at=now - timedelta(hours=2))
    if not should_skip_weekly_summary(state, now=now, timezone="UTC"):
        raise AssertionError("expected skip when already sent this week")

    state = BotState(last_weekly_summary_at=now - timedelta(days=7))
    if should_skip_weekly_summary(state, now=now, timezone="UTC"):
        raise AssertionError("expected send when last weekly was prior week")

    history = PerformanceHistory(
        snapshots=[
            PortfolioPerformanceSnapshot(
                timestamp=now - timedelta(days=7),
                total_value=10_000.0,
                total_cost=9_500.0,
                daily_pnl_pct=0.0,
                positions={"AAPL": PositionPerformancePoint(price=100.0, value=10_000.0)},
            ),
            PortfolioPerformanceSnapshot(
                timestamp=now,
                total_value=10_500.0,
                total_cost=9_500.0,
                daily_pnl_pct=5.0,
                positions={"AAPL": PositionPerformancePoint(price=105.0, value=10_500.0)},
            ),
        ]
    )
    text = format_weekly_summary(
        Portfolio(positions=[Position(ticker="AAPL", shares=10)]),
        performance_history=history,
        lang="en",
    )
    if "Weekly Portfolio Summary" not in text or "7-day return" not in text:
        raise AssertionError(f"unexpected weekly summary text: {text!r}")

    temp_dir = Path(tempfile.mkdtemp(prefix="weekly-summary-test-"))
    try:
        for name in (
            "config.json",
            "portfolio.json",
            "state.json",
            "news_cache.json",
            "ticker_industries.json",
            "ticker_metadata.json",
            "ticker_strategies.json",
            "signals.json",
            "users.json",
            "performance_history.json",
        ):
            src = ROOT / "data" / "examples" / name
            if src.exists():
                shutil.copy(src, temp_dir / name)

        paths = resolve_data_paths(temp_dir)
        repository = DataRepository(paths)
        repository.save_portfolio(
            Portfolio(positions=[Position(ticker="AAPL", shares=10, cost_basis=100.0)])
        )
        repository.save_performance_history(history)
        repository.save_users(
            BotUsers(
                users=[
                    BotUser(
                        chat_id=12345,
                        role="ordinary",
                        language="en",
                    )
                ]
            )
        )

        notifier = RecordingNotifier()
        app_config = AppConfig(enable_weekly_summary=True, timezone="UTC")

        sent = run_weekly_summary(
            repository,
            app_config,
            notifier,  # type: ignore[arg-type]
            force=True,
            now=now,
        )
        if not sent:
            raise AssertionError("expected weekly summary to send")
        if not notifier.calls:
            raise AssertionError("expected notifier calls")
        if not notifier.photos:
            raise AssertionError("expected chart photo delivery")

        loaded = repository.load_state()
        if loaded.last_weekly_summary_at is None:
            raise AssertionError("last_weekly_summary_at should be persisted")

        duplicate = run_weekly_summary(
            repository,
            app_config,
            notifier,  # type: ignore[arg-type]
            now=now + timedelta(hours=1),
        )
        if duplicate:
            raise AssertionError("expected duplicate weekly summary to be skipped")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    print("test_weekly_summary: OK")


if __name__ == "__main__":
    run_test()
