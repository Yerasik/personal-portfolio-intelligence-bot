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
    cost_basis: float | None
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
    """Parse /add_ticker_strategy <TICKER> <long|short> [shares [cost_basis]] <reasoning>."""
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
                cost_basis=None,
                reasoning=reasoning,
            ),
            None,
        )

    shares = 1.0
    cost_basis: float | None = None
    pos = 2
    if pos < len(args):
        try:
            shares = float(args[pos])
            pos += 1
        except ValueError:
            pass
    if pos < len(args):
        try:
            cost_basis = float(args[pos])
            pos += 1
        except ValueError:
            pass
    reasoning = " ".join(args[pos:]).strip()
    if not reasoning:
        return None, "add_ticker_strategy_usage"
    if shares <= 0:
        return None, "add_ticker_strategy_shares_invalid"
    if cost_basis is not None and cost_basis <= 0:
        return None, "add_ticker_strategy_cost_invalid"

    return (
        StrategyAddParseResult(
            ticker=ticker,
            holding_horizon=horizon,
            shares=shares,
            cost_basis=cost_basis,
            reasoning=reasoning,
        ),
        None,
    )
