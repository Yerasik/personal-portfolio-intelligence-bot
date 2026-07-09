"""Pre-event watch reminders and post-event impact checks for catalyst calendar."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from analysis.llm import LlmClient
from analysis.move_explainer import explain_price_move, recent_news_titles_for_ticker
from bot.formatter import format_catalyst_post_event, format_catalyst_pre_event
from bot.notifier import TelegramNotifier
from collectors.catalyst_calendar import default_watch_items, merge_watch_items
from storage.models import (
    AppConfig,
    BotState,
    CatalystEvent,
    CatalystEventsFile,
    CatalystReminderRecord,
    NewsCache,
)
from storage.portfolio_ops import normalize_ticker
from storage.repository import DataRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CatalystReminderDelivery:
    """One catalyst reminder ready for Telegram."""

    event: CatalystEvent
    phase: str
    hours_before: int | None
    message_by_language: dict[str, str]


@dataclass(frozen=True)
class CatalystReminderRunResult:
    """Summary of a catalyst reminder job pass."""

    pre_sent: int = 0
    post_sent: int = 0
    skipped: int = 0


def _reminder_already_sent(
    state: BotState,
    event_id: str,
    *,
    phase: str,
    hours_before: int | None = None,
) -> bool:
    for record in state.catalyst_reminders_sent:
        if record.event_id != event_id or record.phase != phase:
            continue
        if phase == "pre" and record.hours_before != hours_before:
            continue
        return True
    return False


def _related_tickers(event: CatalystEvent, portfolio_tickers: set[str]) -> list[str]:
    if event.tickers:
        return [symbol for symbol in event.tickers if symbol in portfolio_tickers]
    return sorted(portfolio_tickers)


def _hours_until(event_at: datetime, now: datetime) -> float:
    return (event_at - now).total_seconds() / 3600.0


def _hours_since(event_at: datetime, now: datetime) -> float:
    return (now - event_at).total_seconds() / 3600.0


def _price_change_pct(
    ticker: str,
    state: BotState,
    snapshot: dict[str, float],
) -> float | None:
    quote = state.latest_prices.get(ticker)
    if quote is None or quote.price is None:
        return None
    baseline = snapshot.get(ticker)
    if baseline is None or baseline <= 0:
        return None
    return ((quote.price - baseline) / baseline) * 100.0


def build_pre_event_message(
    event: CatalystEvent,
    *,
    hours_before: int,
    lang: str,
    llm: LlmClient | None = None,
    app_config: AppConfig | None = None,
) -> str:
    """Format a localized pre-event watch reminder."""
    watch_items = event.watch_items or merge_watch_items(event.event_type, [])
    llm_note = ""
    if (
        llm is not None
        and app_config is not None
        and app_config.enable_llm_summaries
        and getattr(llm, "is_configured", False)
    ):
        llm_note = _optional_pre_event_llm_note(llm, event, lang, hours_before)
    return format_catalyst_pre_event(
        event,
        hours_before=hours_before,
        watch_items=watch_items,
        llm_note=llm_note,
        lang=lang,
    )


def build_post_event_message(
    event: CatalystEvent,
    *,
    lang: str,
    moves: list[tuple[str, float]],
    llm: LlmClient | None = None,
    app_config: AppConfig | None = None,
    news_cache: NewsCache | None = None,
    state: BotState | None = None,
) -> str:
    """Format a localized post-event impact summary."""
    explanations: list[str] = []
    if llm is not None and app_config is not None and news_cache is not None and state is not None:
        for ticker, pct_change in moves:
            if abs(pct_change) < app_config.catalyst_post_event_move_pct:
                continue
            quote = state.latest_prices.get(ticker)
            headlines = recent_news_titles_for_ticker(news_cache, ticker, limit=5)
            explanation = explain_price_move(
                llm,
                ticker,
                pct_change,
                window="since catalyst",
                news_items=headlines,
                company_name=quote.company_name if quote is not None else "",
                sector=quote.sector if quote is not None else "",
                language=lang,
            )
            explanations.append(explanation.to_message(lang))
    return format_catalyst_post_event(
        event,
        moves=moves,
        explanations=explanations,
        lang=lang,
    )


def _optional_pre_event_llm_note(
    llm: LlmClient,
    event: CatalystEvent,
    lang: str,
    hours_before: int,
) -> str:
    from bot.i18n import llm_language_clause

    tickers = ", ".join(event.tickers) or "portfolio holdings"
    sectors = ", ".join(event.sectors) or "relevant sectors"
    watch = "; ".join(event.watch_items[:6])
    prompt = (
        "You are a cautious portfolio assistant. Write 2-3 short bullet points on what "
        "to monitor before an upcoming market catalyst. Advisory only; no trade instructions.\n\n"
        f"Event: {event.title}\n"
        f"Type: {event.event_type}\n"
        f"In: {hours_before} hour(s)\n"
        f"Tickers: {tickers}\n"
        f"Sectors: {sectors}\n"
        f"Configured watch list: {watch}\n\n"
        f"{llm_language_clause(lang)}\n"
        "Respond with plain text bullets only."
    )
    try:
        text = llm.generate(prompt).strip()
        return text[:600]
    except Exception as exc:
        logger.warning("Pre-event LLM note failed for %s: %s", event.event_id, exc)
        return ""


def collect_due_pre_reminders(
    events: CatalystEventsFile,
    state: BotState,
    app_config: AppConfig,
    portfolio_tickers: set[str],
    *,
    now: datetime | None = None,
) -> list[tuple[CatalystEvent, int]]:
    """Return (event, hours_before) pairs that need a pre-event reminder."""
    current = now or datetime.now(UTC)
    due: list[tuple[CatalystEvent, int]] = []
    for event in events.events:
        hours_left = _hours_until(event.event_at, current)
        if hours_left <= 0:
            continue
        for hours_before in sorted(app_config.catalyst_reminder_hours_before, reverse=True):
            if hours_before <= 0:
                continue
            if hours_left > hours_before:
                continue
            lower_bound = max(hours_before - 2, 0)
            if hours_left < lower_bound:
                continue
            if _reminder_already_sent(
                state,
                event.event_id,
                phase="pre",
                hours_before=hours_before,
            ):
                continue
            if event.event_type == "earnings" and event.tickers:
                if not any(ticker in portfolio_tickers for ticker in event.tickers):
                    continue
            due.append((event, hours_before))
            break
    return due


def collect_due_post_checks(
    events: CatalystEventsFile,
    state: BotState,
    app_config: AppConfig,
    portfolio_tickers: set[str],
    *,
    now: datetime | None = None,
) -> list[CatalystEvent]:
    """Return events that need a post-event impact check."""
    current = now or datetime.now(UTC)
    due: list[CatalystEvent] = []
    for event in events.events:
        hours_since = _hours_since(event.event_at, current)
        if hours_since < 0:
            continue
        if hours_since > app_config.catalyst_post_event_hours:
            continue
        if _reminder_already_sent(state, event.event_id, phase="post"):
            continue
        if event.event_type == "earnings" and event.tickers:
            if not any(ticker in portfolio_tickers for ticker in event.tickers):
                continue
        due.append(event)
    return due


def run_catalyst_reminder_job(
    repository: DataRepository,
    notifier: TelegramNotifier,
    *,
    llm: LlmClient | None = None,
) -> CatalystReminderRunResult:
    """Deliver due pre-event and post-event catalyst reminders."""
    app_config = repository.load_config()
    if not app_config.enable_catalyst_reminders:
        return CatalystReminderRunResult(skipped=1)

    events = repository.load_catalyst_events()
    state = repository.load_state()
    portfolio = repository.load_portfolio()
    news_cache = repository.load_news_cache()
    portfolio_tickers = {
        normalize_ticker(position.ticker) for position in portfolio.positions
    }
    now = datetime.now(UTC)

    pre_sent = 0
    post_sent = 0
    skipped = 0
    reminder_records: list[CatalystReminderRecord] = list(state.catalyst_reminders_sent)
    price_snapshots = dict(state.catalyst_price_snapshots)

    for event, hours_before in collect_due_pre_reminders(
        events,
        state,
        app_config,
        portfolio_tickers,
        now=now,
    ):
        related = _related_tickers(event, portfolio_tickers)
        snapshot: dict[str, float] = {}
        for ticker in related:
            quote = state.latest_prices.get(ticker)
            if quote is not None and quote.price is not None:
                snapshot[ticker] = quote.price
        if snapshot:
            price_snapshots[event.event_id] = snapshot

        users = repository.load_users().users
        delivered = 0
        for user in users:
            message = build_pre_event_message(
                event,
                hours_before=hours_before,
                lang=user.language,
                llm=llm,
                app_config=app_config,
            )
            try:
                notifier.send_text(user.chat_id, message)
            except Exception:
                logger.exception(
                    "Failed to send pre-event catalyst reminder for %s to %s",
                    event.event_id,
                    user.chat_id,
                )
                continue
            delivered += 1
        if delivered:
            reminder_records.append(
                CatalystReminderRecord(
                    event_id=event.event_id,
                    phase="pre",
                    hours_before=hours_before,
                    sent_at=now,
                )
            )
            pre_sent += 1
        else:
            skipped += 1

    for event in collect_due_post_checks(
        events,
        state,
        app_config,
        portfolio_tickers,
        now=now,
    ):
        snapshot = price_snapshots.get(event.event_id, {})
        related = _related_tickers(event, portfolio_tickers)
        moves: list[tuple[str, float]] = []
        for ticker in related:
            pct = _price_change_pct(ticker, state, snapshot)
            if pct is None:
                continue
            moves.append((ticker, pct))

        if not moves and event.event_type != "macro" and event.event_type != "policy":
            skipped += 1
            continue

        users = repository.load_users().users
        delivered = 0
        for user in users:
            message = build_post_event_message(
                event,
                lang=user.language,
                moves=moves,
                llm=llm,
                app_config=app_config,
                news_cache=news_cache,
                state=state,
            )
            try:
                notifier.send_text(user.chat_id, message)
            except Exception:
                logger.exception(
                    "Failed to send post-event catalyst check for %s to %s",
                    event.event_id,
                    user.chat_id,
                )
                continue
            delivered += 1
        if delivered:
            reminder_records.append(
                CatalystReminderRecord(
                    event_id=event.event_id,
                    phase="post",
                    sent_at=now,
                )
            )
            post_sent += 1
        else:
            skipped += 1

    trimmed_records = _trim_reminder_records(reminder_records, now=now)
    repository.save_state(
        state.model_copy(
            update={
                "catalyst_reminders_sent": trimmed_records,
                "catalyst_price_snapshots": _trim_price_snapshots(price_snapshots, now=now),
            }
        )
    )
    return CatalystReminderRunResult(pre_sent=pre_sent, post_sent=post_sent, skipped=skipped)


def _trim_reminder_records(
    records: list[CatalystReminderRecord],
    *,
    now: datetime,
    keep_days: int = 30,
) -> list[CatalystReminderRecord]:
    cutoff = now - timedelta(days=keep_days)
    return [record for record in records if record.sent_at >= cutoff]


def _trim_price_snapshots(
    snapshots: dict[str, dict[str, float]],
    *,
    now: datetime,
    keep_days: int = 14,
) -> dict[str, dict[str, float]]:
    _ = now, keep_days
    if len(snapshots) <= 50:
        return snapshots
    keys = list(snapshots.keys())[-50:]
    return {key: snapshots[key] for key in keys}


def upcoming_events(
    events: CatalystEventsFile,
    *,
    now: datetime | None = None,
    days_ahead: int = 30,
) -> list[CatalystEvent]:
    """Return future catalyst events within a display horizon."""
    current = now or datetime.now(UTC)
    horizon = current + timedelta(days=days_ahead)
    return [
        event
        for event in events.events
        if current - timedelta(hours=6) <= event.event_at <= horizon
    ]
