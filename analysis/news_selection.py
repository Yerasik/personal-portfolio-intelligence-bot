"""Select and deduplicate cached news before LLM summarization."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from storage.models import NewsItem

_SOURCE_SUFFIX_RE = re.compile(
    r"\s*[\-\|\u2013\u2014]\s*"
    r"(Reuters|Bloomberg|CNBC|MarketWatch|Yahoo Finance|Financial Times|"
    r"The Wall Street Journal|WSJ|BBC|AP News|Associated Press|"
    r"South China Morning Post|SCMP|TechCrunch|The Verge|Ars Technica|"
    r"Google News|Business Insider|Investing\.com|Seeking Alpha|"
    r"TipRanks|Stocktwits|Benzinga|Fortune|Forbes|The Guardian).*$",
    flags=re.IGNORECASE,
)
_NON_WORD_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WS_RE = re.compile(r"\s+")
_SIMILARITY_THRESHOLD = 0.55


def _item_timestamp(item: NewsItem) -> datetime:
    value = item.published_at or item.fetched_at
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def normalize_story_title(title: str) -> str:
    """Normalize a headline for duplicate detection across agencies."""
    cleaned = title.strip()
    cleaned = _SOURCE_SUFFIX_RE.sub("", cleaned)
    cleaned = _NON_WORD_RE.sub(" ", cleaned.lower())
    return _WS_RE.sub(" ", cleaned).strip()


def _significant_words(title: str) -> set[str]:
    words = normalize_story_title(title).split()
    return {word for word in words if len(word) >= 3}


def stories_are_similar(left: str, right: str) -> bool:
    """Return True when two headlines likely describe the same story."""
    left_norm = normalize_story_title(left)
    right_norm = normalize_story_title(right)
    if not left_norm or not right_norm:
        return False
    if left_norm == right_norm:
        return True
    if left_norm in right_norm or right_norm in left_norm:
        return True

    left_words = _significant_words(left)
    right_words = _significant_words(right)
    if not left_words or not right_words:
        return False
    overlap = len(left_words & right_words)
    union = len(left_words | right_words)
    return overlap / union >= _SIMILARITY_THRESHOLD


def story_fingerprint(title: str) -> str:
    """Compact key for cross-group duplicate suppression."""
    words = [word for word in normalize_story_title(title).split() if len(word) >= 3]
    if len(words) >= 4:
        return " ".join(words[:8])
    return normalize_story_title(title)


def select_news_for_summary(
    items: list[NewsItem],
    *,
    max_items: int,
    window_hours: int = 48,
    exclude_fingerprints: set[str] | None = None,
    now: datetime | None = None,
) -> tuple[list[NewsItem], set[str]]:
    """Pick recent, unique stories for one sector or ticker summary."""
    evaluated_at = now or datetime.now(tz=UTC)
    cutoff = evaluated_at - timedelta(hours=max(window_hours, 1))
    excluded = set(exclude_fingerprints or ())

    recent = [
        item
        for item in items
        if _item_timestamp(item) >= cutoff
    ]
    recent.sort(key=_item_timestamp, reverse=True)

    selected: list[NewsItem] = []
    added_fingerprints: set[str] = set()

    for item in recent:
        if len(selected) >= max_items:
            break

        fingerprint = story_fingerprint(item.title)
        if fingerprint in excluded or fingerprint in added_fingerprints:
            continue
        if any(stories_are_similar(item.title, kept.title) for kept in selected):
            continue

        selected.append(item)
        added_fingerprints.add(fingerprint)

    return selected, added_fingerprints


def filter_items_in_window(
    items: list[NewsItem],
    *,
    window_hours: int,
    now: datetime | None = None,
) -> list[NewsItem]:
    """Return items published/fetched inside the summary window."""
    evaluated_at = now or datetime.now(tz=UTC)
    cutoff = evaluated_at - timedelta(hours=max(window_hours, 1))
    matched = [item for item in items if _item_timestamp(item) >= cutoff]
    matched.sort(key=_item_timestamp, reverse=True)
    return matched
