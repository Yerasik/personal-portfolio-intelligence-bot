"""Parsing helpers for /chart command arguments."""

from __future__ import annotations

from dataclasses import dataclass

from analysis.ticker_chart import ChartPeriod

_VALID_PERIODS: frozenset[str] = frozenset({"7d", "30d", "90d"})


@dataclass(frozen=True)
class ChartParseResult:
    """Validated /chart arguments."""

    ticker: str
    period: ChartPeriod


def parse_chart_args(args: list[str]) -> tuple[ChartParseResult | None, str | None]:
    """Parse /chart <TICKER> [7d|30d|90d]."""
    if not args:
        return None, "chart_usage"

    ticker = args[0].strip()
    period: ChartPeriod = "30d"

    if len(args) >= 2:
        period_raw = args[1].strip().lower()
        if period_raw not in _VALID_PERIODS:
            return None, "chart_invalid_period"
        period = period_raw  # type: ignore[assignment]

    if len(args) >= 3:
        return None, "chart_usage"

    if not ticker:
        return None, "chart_usage"

    return ChartParseResult(ticker=ticker, period=period), None
