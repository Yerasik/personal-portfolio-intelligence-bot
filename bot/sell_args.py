"""Parsing and validation for /sell_ticker command arguments."""

from __future__ import annotations

import re
from dataclasses import dataclass

from storage.models import Portfolio
from storage.portfolio_ops import normalize_ticker

_PLACEHOLDER_REASONING = frozenset(
    {
        "-",
        "—",
        ".",
        "..",
        "...",
        "n/a",
        "na",
        "none",
        "tbd",
        "x",
        "?",
        "??",
        "skip",
        "test",
    }
)


@dataclass(frozen=True)
class SellParseResult:
    """Validated /sell_ticker arguments."""

    ticker: str
    shares: float | None
    price: float
    reasoning: str
    held_shares: float
    warnings: tuple[str, ...] = ()


def is_valid_sell_reasoning(text: str) -> bool:
    """Return False for empty or placeholder sell rationales."""
    cleaned = text.strip()
    if len(cleaned) < 3:
        return False
    if cleaned.lower() in _PLACEHOLDER_REASONING:
        return False
    if re.fullmatch(r"[-_.!?]+", cleaned):
        return False
    return True


def _position_shares(portfolio: Portfolio, symbol: str) -> float | None:
    normalized = normalize_ticker(symbol)
    for position in portfolio.positions:
        if normalize_ticker(position.ticker) == normalized:
            return position.shares
    return None


def parse_sell_args(
    args: list[str],
    portfolio: Portfolio,
) -> tuple[SellParseResult | None, str | None]:
    """Parse /sell_ticker args; return (result, error_key) when invalid."""
    if len(args) < 3:
        return None, "sell_ticker_usage"

    ticker = args[0]
    symbol = normalize_ticker(ticker)
    held = _position_shares(portfolio, symbol)
    if held is None:
        return None, "sell_ticker_not_held"

    shares: float | None = None
    price: float
    reasoning_start: int

    if len(args) >= 4:
        try:
            shares = float(args[1])
            price = float(args[2])
            reasoning_start = 3
        except ValueError:
            try:
                price = float(args[1])
            except ValueError:
                return None, "sell_ticker_price_invalid"
            shares = None
            reasoning_start = 2
    else:
        try:
            price = float(args[1])
        except ValueError:
            return None, "sell_ticker_price_invalid"
        shares = None
        reasoning_start = 2

    reasoning = " ".join(args[reasoning_start:]).strip()
    if not is_valid_sell_reasoning(reasoning):
        return None, "sell_ticker_reasoning_invalid"

    if shares is not None and shares <= 0:
        return None, "sell_ticker_shares_invalid"
    if price <= 0:
        return None, "sell_ticker_price_invalid"
    if shares is not None and shares > held + 1e-9:
        return None, "sell_ticker_too_many_shares"

    warnings: list[str] = []
    if shares is None:
        warnings.append("sell_warning_sells_all")
        if len(args) == 3:
            middle = args[1]
            try:
                middle_value = float(middle)
            except ValueError:
                middle_value = None
            if (
                middle_value is not None
                and middle_value == int(middle_value)
                and middle_value < held
            ):
                warnings.append("sell_warning_maybe_meant_shares")

    return (
        SellParseResult(
            ticker=symbol,
            shares=shares,
            price=price,
            reasoning=reasoning,
            held_shares=held,
            warnings=tuple(warnings),
        ),
        None,
    )
