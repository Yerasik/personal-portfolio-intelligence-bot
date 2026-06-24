"""Parsing helpers for /add_ticker_strategy command arguments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

HoldingHorizon = Literal["long", "short"]
_HORIZON_VALUES = frozenset({"long", "short"})


@dataclass(frozen=True)
class StrategyAddParseResult:
    """Validated /add_ticker_strategy arguments."""

    ticker: str
    holding_horizon: HoldingHorizon
    shares: float | None
    reasoning: str


def _parse_horizon(token: str) -> HoldingHorizon | None:
    normalized = token.strip().lower()
    if normalized in _HORIZON_VALUES:
        return normalized  # type: ignore[return-value]
    return None


def parse_strategy_add_args(
    args: list[str],
    *,
    ticker_already_held: bool,
) -> tuple[StrategyAddParseResult | None, str | None]:
    """Parse /add_ticker_strategy <TICKER> <long|short> [shares] <reasoning>."""
    if len(args) < 3:
        return None, "add_ticker_strategy_usage"

    ticker = args[0]
    horizon = _parse_horizon(args[1])
    if horizon is None:
        return None, "add_ticker_strategy_horizon_invalid"

    if ticker_already_held:
        reasoning = " ".join(args[2:]).strip()
        if not reasoning:
            return None, "add_ticker_strategy_usage"
        return (
            StrategyAddParseResult(
                ticker=ticker,
                holding_horizon=horizon,
                shares=None,
                reasoning=reasoning,
            ),
            None,
        )

    shares = 1.0
    reasoning_start = 2
    if len(args) >= 4:
        try:
            shares = float(args[2])
            reasoning_start = 3
        except ValueError:
            reasoning_start = 2
    reasoning = " ".join(args[reasoning_start:]).strip()
    if not reasoning:
        return None, "add_ticker_strategy_usage"
    if shares <= 0:
        return None, "add_ticker_strategy_shares_invalid"

    return (
        StrategyAddParseResult(
            ticker=ticker,
            holding_horizon=horizon,
            shares=shares,
            reasoning=reasoning,
        ),
        None,
    )
