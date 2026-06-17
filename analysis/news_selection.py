"""Select and deduplicate cached news before LLM summarization."""

from __future__ import annotations

import re
from dataclasses import dataclass
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


_DEFAULT_MACRO_KEYWORDS: tuple[str, ...] = (
    "federal reserve",
    "fed ",
    " fomc",
    "interest rate",
    "rate cut",
    "rate hike",
    "central bank",
    "ecb",
    "bank of england",
    "pboc",
    "people's bank of china",
    "monetary policy",
    "inflation",
    "cpi",
    "gdp",
    "treasury yield",
    "bond yield",
    "macroeconomic",
    "recession",
    "stimulus",
    "quantitative easing",
    "liquidity",
    "banking sector",
    "financial stability",
)


def _text_matches_keyword(text: str, keyword: str) -> bool:
    term = keyword.strip().lower()
    if not term:
        return False
    haystack = text.lower()
    if " " in term or term.endswith(" "):
        return term in haystack
    return bool(re.search(rf"\b{re.escape(term)}\b", haystack))


def macro_sector_keywords(sector_keywords: dict[str, list[str]], label: str) -> list[str]:
    """Return macro/bank keywords from config, with sensible defaults."""
    configured = sector_keywords.get(label, [])
    if configured:
        return configured
    return list(_DEFAULT_MACRO_KEYWORDS)


def article_matches_macro(text: str, keywords: list[str]) -> bool:
    """Return True when headline text matches macro/central-bank keywords."""
    return any(_text_matches_keyword(text, keyword) for keyword in keywords)


def is_macro_article(
    item: NewsItem,
    macro_label: str,
    macro_keywords: list[str],
    *,
    text: str | None = None,
) -> bool:
    """Return True when an article belongs to the macro/central-bank bucket."""
    label = macro_label.strip()
    if not label:
        return False
    body = text if text is not None else f"{item.title} {item.summary}".strip()
    return label in item.sector_tags or article_matches_macro(body, macro_keywords)


def articles_matching_sector(
    items: list[NewsItem],
    sector: str,
    *,
    macro_label: str = "",
    macro_keywords: list[str] | None = None,
) -> list[NewsItem]:
    """Return cache items for a sector; macro also matches keyword-tagged stories."""
    label = sector.strip()
    if not label:
        return []
    if macro_label and label == macro_label.strip():
        keywords = macro_keywords or []
        return [
            item
            for item in items
            if is_macro_article(item, macro_label, keywords)
        ]
    return [item for item in items if label in item.sector_tags]


def display_label_for_article(
    item: NewsItem,
    portfolio_symbols: set[str],
) -> str:
    """Pick a short category label for a headline bullet."""
    ticker_hits = [symbol for symbol in item.ticker_tags if symbol in portfolio_symbols]
    if ticker_hits:
        return ticker_hits[0]
    if item.sector_tags:
        return item.sector_tags[0]
    if item.ticker_tags:
        return item.ticker_tags[0]
    source = item.source.strip()
    return source or "News"


@dataclass(frozen=True)
class RankedNewsItem:
    """News article with importance score and display category."""

    item: NewsItem
    label: str
    score: float


def select_top_important_articles(
    items: list[NewsItem],
    *,
    portfolio_symbols: set[str],
    focus_sectors: set[str],
    macro_label: str,
    macro_keywords: list[str],
    max_items: int = 5,
    window_hours: int = 48,
    now: datetime | None = None,
) -> list[RankedNewsItem]:
    """Rank portfolio, sector, and macro news; return deduplicated top headlines."""
    recent = filter_items_in_window(items, window_hours=window_hours, now=now)
    ranked: list[RankedNewsItem] = []

    for item in recent:
        text = f"{item.title} {item.summary}".strip()
        label = _primary_label(
            item,
            portfolio_symbols=portfolio_symbols,
            focus_sectors=focus_sectors,
            macro_label=macro_label,
            macro_keywords=macro_keywords,
            text=text,
        )
        if label is None:
            continue

        age_hours = max(
            0.0,
            (
                (now or datetime.now(tz=UTC)) - _item_timestamp(item)
            ).total_seconds()
            / 3600.0,
        )
        recency_boost = max(0.0, 24.0 - age_hours) / 24.0 * 4.0
        score = _relevance_weight(label, item, macro_label) + recency_boost
        if item.sentiment is not None and item.sentiment < 0:
            score += 1.5
        ranked.append(RankedNewsItem(item=item, label=label, score=score))

    ranked.sort(key=lambda row: row.score, reverse=True)

    selected: list[RankedNewsItem] = []
    seen_fingerprints: set[str] = set()
    for row in ranked:
        if len(selected) >= max_items:
            break
        fingerprint = story_fingerprint(row.item.title)
        if fingerprint in seen_fingerprints:
            continue
        if any(stories_are_similar(row.item.title, kept.item.title) for kept in selected):
            continue
        selected.append(row)
        seen_fingerprints.add(fingerprint)

    return selected


def select_top_global_articles(
    items: list[NewsItem],
    *,
    portfolio_symbols: set[str],
    macro_label: str,
    macro_keywords: list[str],
    max_items: int = 5,
    window_hours: int = 48,
    now: datetime | None = None,
) -> list[RankedNewsItem]:
    """Rank all cached articles by importance; exclude macro/central-bank stories."""
    recent = filter_items_in_window(items, window_hours=window_hours, now=now)
    ranked: list[RankedNewsItem] = []
    evaluated_at = now or datetime.now(tz=UTC)

    for item in recent:
        text = f"{item.title} {item.summary}".strip()
        if is_macro_article(item, macro_label, macro_keywords, text=text):
            continue

        age_hours = max(
            0.0,
            (evaluated_at - _item_timestamp(item)).total_seconds() / 3600.0,
        )
        recency_boost = max(0.0, 24.0 - age_hours) / 24.0 * 4.0
        score = _global_importance_score(item, portfolio_symbols) + recency_boost
        if item.sentiment is not None and item.sentiment < 0:
            score += 1.5

        ranked.append(
            RankedNewsItem(
                item=item,
                label=display_label_for_article(item, portfolio_symbols),
                score=score,
            )
        )

    ranked.sort(key=lambda row: row.score, reverse=True)

    selected: list[RankedNewsItem] = []
    seen_fingerprints: set[str] = set()
    for row in ranked:
        if len(selected) >= max_items:
            break
        fingerprint = story_fingerprint(row.item.title)
        if fingerprint in seen_fingerprints:
            continue
        if any(stories_are_similar(row.item.title, kept.item.title) for kept in selected):
            continue
        selected.append(row)
        seen_fingerprints.add(fingerprint)

    return selected


def _global_importance_score(item: NewsItem, portfolio_symbols: set[str]) -> float:
    """Heuristic importance from tag breadth and portfolio overlap."""
    score = 4.0
    score += len(item.ticker_tags) * 1.5
    score += len(item.sector_tags) * 1.0
    if any(symbol in portfolio_symbols for symbol in item.ticker_tags):
        score += 3.0
    return score


def _primary_label(
    item: NewsItem,
    *,
    portfolio_symbols: set[str],
    focus_sectors: set[str],
    macro_label: str,
    macro_keywords: list[str],
    text: str,
) -> str | None:
    """Pick the best display label for a relevant article."""
    ticker_hits = [symbol for symbol in item.ticker_tags if symbol in portfolio_symbols]
    if ticker_hits:
        return ticker_hits[0]

    sector_hits = [sector for sector in item.sector_tags if sector in focus_sectors]
    if sector_hits:
        return sector_hits[0]

    if macro_label in item.sector_tags or article_matches_macro(text, macro_keywords):
        return macro_label

    return None


def _relevance_weight(label: str, item: NewsItem, macro_label: str) -> float:
    if label in item.ticker_tags:
        return 10.0
    if label == macro_label:
        return 8.0
    if label in item.sector_tags:
        return 6.0
    return 4.0
