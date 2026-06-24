"""Parsing helpers for /add_ticker command arguments."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AddTickerParseResult:
    """Validated /add_ticker arguments."""

    ticker: str
    shares: float
    cost_basis: float | None


def parse_add_ticker_args(args: list[str]) -> tuple[AddTickerParseResult | None, str | None]:
    """Parse /add_ticker <TICKER> [shares [cost_basis]]."""
    if not args:
        return None, "add_ticker_usage"

    ticker = args[0]
    shares = 1.0
    cost_basis: float | None = None
    pos = 1

    if pos < len(args):
        try:
            shares = float(args[pos])
            pos += 1
        except ValueError:
            return None, "add_ticker_shares_invalid"

    if pos < len(args):
        try:
            cost_basis = float(args[pos])
            pos += 1
        except ValueError:
            return None, "add_ticker_cost_invalid"

    if pos < len(args):
        return None, "add_ticker_usage"

    if shares <= 0:
        return None, "add_ticker_shares_invalid"
    if cost_basis is not None and cost_basis <= 0:
        return None, "add_ticker_cost_invalid"

    return AddTickerParseResult(ticker=ticker, shares=shares, cost_basis=cost_basis), None
