"""Catalyst calendar collection: earnings dates and manual macro/policy events."""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import yfinance as yf

from collectors.base import BaseCollector, CollectorContext, CollectorResult
from collectors.market_data import _quiet_yfinance, tracked_tickers
from storage.models import (
    AppConfig,
    CatalystEvent,
    CatalystEventsFile,
    ManualCatalystEvent,
)
from storage.portfolio_ops import normalize_ticker

logger = logging.getLogger(__name__)

_DEFAULT_WATCH_ITEMS: dict[str, list[str]] = {
    "earnings": [
        "Revenue and EPS vs consensus",
        "Forward guidance and margin outlook",
        "Segment demand commentary",
        "Inventory / capex signals",
    ],
    "macro": [
        "Headline vs economist expectations",
        "Rates, FX, and liquidity reaction",
        "Knock-on effects on portfolio sectors",
        "Central bank tone and forward guidance",
    ],
    "policy": [
        "Scope and enforcement timeline",
        "Supply-chain / export-control impact",
        "Affected tickers and geographies",
        "Market repricing in semis and China-US names",
    ],
}


def catalyst_event_id(
    title: str,
    event_at: datetime,
    tickers: list[str],
) -> str:
    """Stable id for deduplicating calendar rows."""
    key = f"{title.strip().lower()}|{event_at.isoformat()}|{','.join(sorted(tickers))}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def parse_config_event_datetime(value: str, timezone: str) -> datetime:
    """Parse manual event timestamps in the configured timezone."""
    cleaned = value.strip()
    tz = ZoneInfo(timezone)
    if "T" in cleaned:
        parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=tz)
        return parsed.astimezone(UTC)
    parsed_date = datetime.fromisoformat(cleaned)
    return datetime(
        parsed_date.year,
        parsed_date.month,
        parsed_date.day,
        9,
        0,
        tzinfo=tz,
    ).astimezone(UTC)


def default_watch_items(event_type: str) -> list[str]:
    """Return deterministic watch-list bullets for a catalyst type."""
    return list(_DEFAULT_WATCH_ITEMS.get(event_type, _DEFAULT_WATCH_ITEMS["macro"]))


def merge_watch_items(event_type: str, configured: list[str]) -> list[str]:
    """Combine configured watch bullets with type defaults (deduped)."""
    merged: list[str] = []
    seen: set[str] = set()
    for item in [*configured, *default_watch_items(event_type)]:
        cleaned = item.strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(cleaned)
    return merged


def _coerce_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    try:
        if hasattr(value, "to_pydatetime"):
            dt = value.to_pydatetime()
        elif isinstance(value, datetime):
            dt = value
        else:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except (TypeError, ValueError):
        return None


def fetch_earnings_events(
    symbol: str,
    *,
    now: datetime,
    horizon_days: int,
) -> list[CatalystEvent]:
    """Best-effort earnings dates for one ticker via yfinance."""
    normalized = normalize_ticker(symbol)
    horizon_end = now + timedelta(days=horizon_days)
    events: list[CatalystEvent] = []

    with _quiet_yfinance():
        ticker = yf.Ticker(normalized)
        candidates: list[datetime] = []

        try:
            calendar = ticker.calendar
            if isinstance(calendar, dict):
                raw_dates = calendar.get("Earnings Date") or calendar.get("EarningsDate")
                if raw_dates is not None:
                    if isinstance(raw_dates, (list, tuple)):
                        for item in raw_dates:
                            dt = _coerce_datetime(item)
                            if dt is not None:
                                candidates.append(dt)
                    else:
                        dt = _coerce_datetime(raw_dates)
                        if dt is not None:
                            candidates.append(dt)
        except Exception as exc:
            logger.debug("yfinance calendar unavailable for %s: %s", normalized, exc)

        try:
            earnings_dates = ticker.get_earnings_dates(limit=6)
            if earnings_dates is not None and not getattr(earnings_dates, "empty", True):
                for index in earnings_dates.index:
                    dt = _coerce_datetime(index)
                    if dt is not None:
                        candidates.append(dt)
        except Exception as exc:
            logger.debug("yfinance earnings_dates unavailable for %s: %s", normalized, exc)

    seen: set[str] = set()
    for event_at in candidates:
        if event_at < now - timedelta(days=1) or event_at > horizon_end:
            continue
        title = f"{normalized} earnings"
        event_id = catalyst_event_id(title, event_at, [normalized])
        if event_id in seen:
            continue
        seen.add(event_id)
        events.append(
            CatalystEvent(
                event_id=event_id,
                title=title,
                event_type="earnings",
                event_at=event_at,
                tickers=[normalized],
                watch_items=default_watch_items("earnings"),
                source="yfinance",
            )
        )
    return events


def manual_event_to_catalyst(
    manual: ManualCatalystEvent,
    *,
    timezone: str,
) -> CatalystEvent | None:
    """Convert a config.json manual row into a CatalystEvent."""
    try:
        event_at = parse_config_event_datetime(manual.event_at, timezone)
    except ValueError as exc:
        logger.warning("Skipping invalid manual catalyst event %r: %s", manual.title, exc)
        return None

    tickers = [normalize_ticker(symbol) for symbol in manual.tickers if symbol.strip()]
    sectors = [sector.strip() for sector in manual.sectors if sector.strip()]
    event_id = catalyst_event_id(manual.title, event_at, tickers)
    return CatalystEvent(
        event_id=event_id,
        title=manual.title.strip(),
        event_type=manual.event_type,
        event_at=event_at,
        tickers=tickers,
        sectors=sectors,
        watch_items=merge_watch_items(manual.event_type, manual.watch_items),
        source="config",
        notes=manual.notes.strip(),
    )


def build_catalyst_calendar(
    app_config: AppConfig,
    symbols: list[str],
    *,
    now: datetime | None = None,
) -> CatalystEventsFile:
    """Merge yfinance earnings and manual config events into one calendar."""
    current = now or datetime.now(UTC)
    horizon = app_config.catalyst_calendar_days_ahead
    merged: dict[str, CatalystEvent] = {}

    for symbol in symbols:
        for event in fetch_earnings_events(symbol, now=current, horizon_days=horizon):
            merged[event.event_id] = event

    for manual in app_config.manual_catalyst_events:
        event = manual_event_to_catalyst(manual, timezone=app_config.timezone)
        if event is None:
            continue
        if event.event_at < current - timedelta(days=1):
            continue
        if event.event_at > current + timedelta(days=horizon):
            continue
        merged[event.event_id] = event

    events = sorted(merged.values(), key=lambda item: item.event_at)
    return CatalystEventsFile(events=events, updated_at=current)


class CatalystCalendarCollector(BaseCollector):
    """Refresh catalyst_events.json from portfolio tickers and config."""

    name = "catalyst_calendar"

    def run(self, context: CollectorContext) -> CollectorResult:
        symbols = tracked_tickers(
            context.portfolio,
            extra_watchlist=context.app_config.extra_watchlist,
        )
        calendar = build_catalyst_calendar(context.app_config, symbols)
        context.repository.save_catalyst_events(calendar)
        earnings = sum(1 for event in calendar.events if event.event_type == "earnings")
        other = len(calendar.events) - earnings
        return CollectorResult(
            name=self.name,
            success=True,
            message=(
                f"Cached {len(calendar.events)} catalyst event(s) "
                f"({earnings} earnings, {other} macro/policy) for {len(symbols)} ticker(s)"
            ),
        )
