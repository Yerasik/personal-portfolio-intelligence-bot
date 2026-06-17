"""Morning/evening deep portfolio digest backed by Ollama."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from analysis.llm import LlmClient
from analysis.news_selection import filter_items_in_window
from collectors.market_data import portfolio_tickers
from storage.models import AppConfig, BotState, NewsCache, SignalsFile
from storage.portfolio_ops import normalize_ticker
from storage.repository import DataRepository

logger = logging.getLogger(__name__)

HEADLINE_WINDOW_HOURS = 24
_MAX_HEADLINES_PER_TICKER = 8

_DEEP_DIGEST_PROMPT = """\
You are a portfolio analyst writing a morning/evening brief.

Portfolio signals:
{per_ticker_signals_block}

Write a structured brief:
MARKET CONTEXT: 2 sentences on macro themes visible in the news.
TICKER HIGHLIGHTS: one bullet per ticker with the key signal.
WATCH LIST: 1–2 tickers that need attention today and why.

Be concise. No disclaimer.
"""


@dataclass(frozen=True)
class TickerDigestSignals:
    """Inputs assembled for one holding."""

    ticker: str
    headlines: list[str]
    sentiment_score: float | None
    sentiment_delta: float | None
    price_change_pct: float | None
    pros_cons_memo: str | None


def parse_deep_digest_time(value: str) -> tuple[int, int]:
    """Parse HH:MM schedule strings from config.json."""
    cleaned = value.strip()
    parts = cleaned.split(":", maxsplit=1)
    if len(parts) != 2:
        raise ValueError(f"invalid deep digest time: {value!r}")
    hour = int(parts[0])
    minute = int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"invalid deep digest time: {value!r}")
    return hour, minute


def latest_scheduled_slot_before(
    now: datetime,
    schedule_times: list[str],
    timezone: str,
) -> datetime | None:
    """Return the most recent configured digest slot at or before ``now``."""
    tz = ZoneInfo(timezone)
    local_now = now.astimezone(tz)
    candidates: list[datetime] = []

    for day_offset in (0, 1):
        day = (local_now.date() - timedelta(days=day_offset))
        for time_str in schedule_times:
            try:
                hour, minute = parse_deep_digest_time(time_str)
            except ValueError:
                continue
            slot = datetime(
                day.year,
                day.month,
                day.day,
                hour,
                minute,
                tzinfo=tz,
            )
            if slot <= local_now:
                candidates.append(slot)

    if not candidates:
        return None
    return max(candidates)


def should_skip_deep_digest(
    state: BotState,
    *,
    now: datetime,
    schedule_times: list[str],
    timezone: str,
) -> bool:
    """Skip when this scheduled slot was already delivered."""
    if state.digest_sent_at is None:
        return False

    slot = latest_scheduled_slot_before(now, schedule_times, timezone)
    if slot is None:
        return False

    sent_at = state.digest_sent_at
    if sent_at.tzinfo is None:
        sent_at = sent_at.replace(tzinfo=UTC)
    return sent_at.astimezone(slot.tzinfo) >= slot


def headlines_for_ticker(
    news_cache: NewsCache,
    ticker: str,
    *,
    now: datetime | None = None,
) -> list[str]:
    """Return deduplicated headline titles for one ticker in the last 24 hours."""
    symbol = normalize_ticker(ticker)
    matched = [
        item
        for item in news_cache.items
        if symbol in item.ticker_tags
    ]
    recent = filter_items_in_window(
        matched,
        window_hours=HEADLINE_WINDOW_HOURS,
        now=now,
    )
    titles: list[str] = []
    seen: set[str] = set()
    for item in recent:
        title = item.title.strip()
        if not title or title in seen:
            continue
        seen.add(title)
        titles.append(title)
        if len(titles) >= _MAX_HEADLINES_PER_TICKER:
            break
    return titles


def assemble_ticker_signals(
    portfolio_tickers_list: list[str],
    *,
    news_cache: NewsCache,
    signals: SignalsFile,
    state: BotState,
    now: datetime | None = None,
) -> list[TickerDigestSignals]:
    """Build per-ticker signal blocks for the deep digest prompt."""
    evaluated_at = now or datetime.now(tz=UTC)
    rows: list[TickerDigestSignals] = []

    for ticker in portfolio_tickers_list:
        symbol = normalize_ticker(ticker)
        headlines = headlines_for_ticker(news_cache, symbol, now=evaluated_at)

        sentiment_record = signals.sentiment.get(symbol)
        sentiment_score = sentiment_record.score if sentiment_record else None
        previous_sentiment = state.deep_digest_sentiment_snapshot.get(symbol)
        sentiment_delta = None
        if sentiment_score is not None and previous_sentiment is not None:
            sentiment_delta = sentiment_score - previous_sentiment

        quote = state.latest_prices.get(symbol)
        price_change_pct = _price_change_since_digest(symbol, quote, state)

        memo_record = signals.pros_cons.get(symbol)
        pros_cons_memo = memo_record.memo.strip() if memo_record else None

        rows.append(
            TickerDigestSignals(
                ticker=symbol,
                headlines=headlines,
                sentiment_score=sentiment_score,
                sentiment_delta=sentiment_delta,
                price_change_pct=price_change_pct,
                pros_cons_memo=pros_cons_memo,
            )
        )

    return rows


def format_per_ticker_signals_block(rows: list[TickerDigestSignals]) -> str:
    """Render the prompt block describing each holding."""
    sections: list[str] = []
    for row in rows:
        lines = [f"{row.ticker}:"]
        if row.headlines:
            lines.append("  Headlines (24h):")
            lines.extend(f"  - {title}" for title in row.headlines)
        else:
            lines.append("  Headlines (24h): none")

        if row.sentiment_score is not None:
            if row.sentiment_delta is not None:
                lines.append(
                    f"  Sentiment: {row.sentiment_score:+.2f} "
                    f"(delta since last digest: {row.sentiment_delta:+.2f})"
                )
            else:
                lines.append(f"  Sentiment: {row.sentiment_score:+.2f}")
        else:
            lines.append("  Sentiment: n/a")

        if row.price_change_pct is not None:
            lines.append(
                f"  Price change since last digest: {row.price_change_pct:+.2f}%"
            )
        else:
            lines.append("  Price change since last digest: n/a")

        if row.pros_cons_memo:
            lines.append(f"  Pros/cons memo: {row.pros_cons_memo}")
        else:
            lines.append("  Pros/cons memo: none")

        sections.append("\n".join(lines))

    return "\n\n".join(sections) if sections else "No holdings."


def build_deep_digest_prompt(
    rows: list[TickerDigestSignals],
    *,
    language: str = "en",
) -> str:
    """Build the Ollama prompt for the deep digest."""
    from bot.i18n import llm_language_clause

    block = format_per_ticker_signals_block(rows)
    language_clause = llm_language_clause(language)
    prompt = _DEEP_DIGEST_PROMPT.format(per_ticker_signals_block=block)
    if language_clause:
        return f"{prompt}\n\n{language_clause}"
    return prompt


def build_plain_fallback_digest(
    rows: list[TickerDigestSignals],
    *,
    lang: str = "en",
) -> str:
    """Plain-text digest when Ollama is unavailable."""
    from bot.i18n import t

    lines = [t("deep_digest_fallback_title", lang), ""]
    for row in rows:
        lines.append(f"{row.ticker}:")
        if row.sentiment_score is not None:
            detail = f"sentiment {row.sentiment_score:+.2f}"
            if row.sentiment_delta is not None:
                detail += f" (delta {row.sentiment_delta:+.2f})"
            lines.append(f"  {detail}")
        else:
            lines.append("  sentiment n/a")
        if row.price_change_pct is not None:
            lines.append(f"  price change since last digest: {row.price_change_pct:+.2f}%")
        else:
            lines.append("  price change since last digest: n/a")
        lines.append("")
    return "\n".join(lines).strip()


def generate_deep_digest_messages(
    llm: LlmClient,
    repository: DataRepository,
    app_config: AppConfig,
    *,
    languages: set[str],
    now: datetime | None = None,
) -> dict[str, str]:
    """Generate localized deep digest text for each language."""
    portfolio = repository.load_portfolio()
    symbols = portfolio_tickers(portfolio)
    if not symbols:
        return {}

    state = repository.load_state()
    signals = repository.load_signals()
    news_cache = repository.load_news_cache()
    evaluated_at = now or datetime.now(tz=UTC)
    rows = assemble_ticker_signals(
        symbols,
        news_cache=news_cache,
        signals=signals,
        state=state,
        now=evaluated_at,
    )

    messages: dict[str, str] = {}
    for language in sorted(languages):
        if app_config.enable_llm_summaries and llm.is_configured:
            try:
                prompt = build_deep_digest_prompt(rows, language=language)
                text = llm.generate(prompt).strip()
                if text:
                    messages[language] = text
                    continue
            except Exception as exc:
                logger.warning(
                    "Deep digest LLM failed for lang=%s: %s",
                    language,
                    exc,
                )
        messages[language] = build_plain_fallback_digest(rows, lang=language)

    return messages


def record_deep_digest_delivery(
    repository: DataRepository,
    *,
    delivered_at: datetime | None = None,
) -> None:
    """Persist digest_sent_at and snapshots used for next-run deltas."""
    now = delivered_at or datetime.now(tz=UTC)
    state = repository.load_state()
    signals = repository.load_signals()
    portfolio = repository.load_portfolio()

    price_snapshot: dict[str, float] = {}
    sentiment_snapshot: dict[str, float] = {}

    for symbol in portfolio_tickers(portfolio):
        quote = state.latest_prices.get(symbol)
        if quote is not None and quote.price is not None:
            price_snapshot[symbol] = quote.price
        sentiment_record = signals.sentiment.get(symbol)
        if sentiment_record is not None:
            sentiment_snapshot[symbol] = sentiment_record.score

    state.digest_sent_at = now
    state.deep_digest_price_snapshot = price_snapshot
    state.deep_digest_sentiment_snapshot = sentiment_snapshot
    repository.save_state(state)


def run_deep_digest(
    repository: DataRepository,
    llm: LlmClient,
    app_config: AppConfig,
    notifier,
    *,
    now: datetime | None = None,
    force: bool = False,
) -> bool:
    """Build and deliver the deep digest; return True when at least one send succeeded."""
    evaluated_at = now or datetime.now(tz=UTC)
    schedule_times = list(app_config.deep_digest_times)

    if not schedule_times:
        logger.info("Deep digest skipped: no deep_digest_times configured")
        return False

    state = repository.load_state()
    if not force and should_skip_deep_digest(
        state,
        now=evaluated_at,
        schedule_times=schedule_times,
        timezone=app_config.timezone,
    ):
        logger.info("Deep digest skipped: already sent for current slot")
        return False

    users = repository.load_users().users
    languages = {user.language for user in users} or {"en"}
    messages = generate_deep_digest_messages(
        llm,
        repository,
        app_config,
        languages=languages,
        now=evaluated_at,
    )
    if not messages:
        logger.info("Deep digest skipped: no portfolio holdings")
        return False

    sent = notifier.deliver_deep_digest(repository, messages)
    if sent:
        record_deep_digest_delivery(repository, delivered_at=evaluated_at)
        logger.info("Deep digest delivered")
    else:
        logger.warning("Deep digest was not delivered")
    return sent


def _price_change_since_digest(
    symbol: str,
    quote,
    state: BotState,
) -> float | None:
    """Compute percent move since the previous deep digest snapshot."""
    previous_price = state.deep_digest_price_snapshot.get(symbol)
    if quote is None:
        return None
    if previous_price and quote.price is not None and previous_price > 0:
        return ((quote.price - previous_price) / previous_price) * 100.0
    if quote.change_pct is not None:
        return quote.change_pct
    return None
