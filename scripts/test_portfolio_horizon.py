#!/usr/bin/env python3
"""Tests for long/short portfolio grouping."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.formatter import format_portfolio, format_strategy_list
from storage.models import BotState, Portfolio, Position, TickerStrategy


def _strategy(ticker: str, horizon: str) -> TickerStrategy:
    now = datetime.now(tz=UTC)
    return TickerStrategy(
        ticker=ticker,
        developer_reasoning="internal",
        strategy_text=f"Thesis for {ticker}",
        holding_horizon=horizon,  # type: ignore[arg-type]
        created_at=now,
        updated_at=now,
    )


def run_test() -> None:
    portfolio = Portfolio(
        positions=[
            Position(ticker="SHORT1", shares=10),
            Position(ticker="LONG1", shares=5),
            Position(ticker="LONG2", shares=3),
        ]
    )
    strategies = {
        "SHORT1": _strategy("SHORT1", "short"),
        "LONG1": _strategy("LONG1", "long"),
        "LONG2": _strategy("LONG2", "long"),
    }
    state = BotState()

    portfolio_text = format_portfolio(
        portfolio,
        state,
        strategies=strategies,
        lang="en",
    )
    long_idx = portfolio_text.index("Long-term holdings")
    short_idx = portfolio_text.index("Short-term holdings")
    if long_idx > short_idx:
        raise AssertionError("long-term section should appear before short-term section")
    if portfolio_text.index("LONG1") > portfolio_text.index("SHORT1"):
        raise AssertionError("long holdings should be listed before short holdings")

    strategy_text = format_strategy_list(portfolio, strategies, lang="en")
    if "Long-term holdings" not in strategy_text or "Short-term holdings" not in strategy_text:
        raise AssertionError(f"strategy list should be grouped: {strategy_text}")

    print("Portfolio horizon grouping checks passed.")


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
