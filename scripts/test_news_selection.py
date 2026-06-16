#!/usr/bin/env python3
"""Smoke tests for news deduplication and selection."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.news_selection import (
    normalize_story_title,
    select_news_for_summary,
    stories_are_similar,
)
from storage.models import NewsItem

NOW = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)


def _item(item_id: str, title: str, *, published_at: datetime | None = None) -> NewsItem:
    when = published_at or NOW
    return NewsItem(
        id=item_id,
        title=title,
        source="Test",
        url=f"https://example.com/{item_id}",
        published_at=when,
        fetched_at=when,
        ticker_tags=[],
        sector_tags=[],
        summary="",
    )


def run_test() -> None:
    left = "Apple unveils new iPhone - Reuters"
    right = "Apple unveils new iPhone | Bloomberg"
    if not stories_are_similar(left, right):
        raise AssertionError("expected similar agency variants to match")
    if normalize_story_title(left) != normalize_story_title(
        "Apple unveils new iPhone"
    ):
        raise AssertionError("agency suffix should be stripped")

    duplicates = [
        _item("a", "Apple unveils new iPhone - Reuters", published_at=NOW - timedelta(hours=1)),
        _item("b", "Apple unveils new iPhone | Bloomberg", published_at=NOW - timedelta(hours=2)),
        _item("c", "Microsoft cloud revenue beats estimates", published_at=NOW - timedelta(hours=3)),
    ]
    selected, fingerprints = select_news_for_summary(
        duplicates,
        max_items=5,
        window_hours=48,
        now=NOW,
    )
    if len(selected) != 2:
        raise AssertionError(f"expected 2 unique stories, got {len(selected)}")
    if selected[0].id != "a":
        raise AssertionError("newest duplicate should be kept")
    if len(fingerprints) != 2:
        raise AssertionError("fingerprints should track unique stories")

    stale = _item(
        "old",
        "Stale headline",
        published_at=NOW - timedelta(hours=72),
    )
    recent_only, _ = select_news_for_summary(
        [stale, duplicates[2]],
        max_items=5,
        window_hours=24,
        now=NOW,
    )
    if len(recent_only) != 1 or recent_only[0].id != "c":
        raise AssertionError("stale items should be filtered by window")

    first, fps = select_news_for_summary(duplicates, max_items=5, window_hours=48, now=NOW)
    second, _ = select_news_for_summary(
        duplicates,
        max_items=5,
        window_hours=48,
        exclude_fingerprints=fps,
        now=NOW,
    )
    if second:
        raise AssertionError("excluded fingerprints should suppress repeats")

    print("News selection checks passed.")


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
