#!/usr/bin/env python3
"""Smoke tests for catalyst calendar collection and reminders."""

from __future__ import annotations

import shutil
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.catalyst_reminders import (
    build_pre_event_message,
    collect_due_pre_reminders,
    upcoming_events,
)
from collectors.catalyst_calendar import (
    build_catalyst_calendar,
    catalyst_event_id,
    manual_event_to_catalyst,
    merge_watch_items,
    parse_config_event_datetime,
)
from storage.models import (
    AppConfig,
    BotState,
    CatalystEvent,
    CatalystEventsFile,
    ManualCatalystEvent,
    Portfolio,
    Position,
    PositionLot,
)
from storage.paths import resolve_data_paths
from storage.repository import DataRepository


def run_test() -> None:
    tz = "Asia/Hong_Kong"
    now = datetime(2026, 7, 9, 2, 0, tzinfo=UTC)
    event_at = now + timedelta(hours=23)
    manual = ManualCatalystEvent(
        title="FOMC decision",
        event_type="macro",
        event_at="2026-07-10T14:00:00",
        sectors=["Macro & Central Banks"],
        watch_items=["Dot plot", "Powell tone"],
    )
    parsed = manual_event_to_catalyst(manual, timezone=tz)
    if parsed is None:
        raise AssertionError("manual event should parse")
    if parsed.event_type != "macro":
        raise AssertionError("expected macro event")

    dt = parse_config_event_datetime("2026-08-01", tz)
    if dt.hour != 1:  # 09:00 HKT -> UTC
        raise AssertionError(f"unexpected default time: {dt}")

    watch = merge_watch_items("policy", ["Export scope"])
    if "Export scope" not in watch:
        raise AssertionError("configured watch item missing")

    portfolio = Portfolio(
        positions=[
            Position(
                ticker="MU",
                lots=[PositionLot(shares=1, cost=100.0, date="2026-07-09")],
            )
        ]
    )
    app_config = AppConfig(
        timezone=tz,
        manual_catalyst_events=[manual],
        catalyst_reminder_hours_before=[24, 2],
    )

    with patch(
        "collectors.catalyst_calendar.fetch_earnings_events",
        return_value=[
            CatalystEvent(
                event_id=catalyst_event_id("MU earnings", event_at, ["MU"]),
                title="MU earnings",
                event_type="earnings",
                event_at=event_at,
                tickers=["MU"],
                watch_items=watch,
                source="test",
            )
        ],
    ):
        calendar = build_catalyst_calendar(app_config, ["MU"], now=now)

    if len(calendar.events) < 2:
        raise AssertionError(f"expected earnings + manual events, got {len(calendar.events)}")

    state = BotState()
    due = collect_due_pre_reminders(
        calendar,
        state,
        app_config,
        {"MU"},
        now=now,
    )
    if not due:
        raise AssertionError("24h pre-reminder should be due")

    message = build_pre_event_message(
        due[0][0],
        hours_before=24,
        lang="en",
    )
    if "What to watch" not in message:
        raise AssertionError(f"pre-event message missing watch list: {message}")

    upcoming = upcoming_events(calendar, now=now, days_ahead=30)
    if not upcoming:
        raise AssertionError("upcoming events should not be empty")

    temp_dir = Path(tempfile.mkdtemp(prefix="catalyst-test-"))
    try:
        paths = resolve_data_paths(temp_dir)
        repo = DataRepository(paths)
        repo.save_catalyst_events(calendar)
        loaded = repo.load_catalyst_events()
        if len(loaded.events) != len(calendar.events):
            raise AssertionError("catalyst events did not persist")
        print("Catalyst calendar checks passed.")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
