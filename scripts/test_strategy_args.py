#!/usr/bin/env python3
"""Tests for /add_ticker_strategy argument parsing."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.strategy_args import parse_strategy_add_args


def run_test() -> None:
    parsed_new, err = parse_strategy_add_args(
        ["NVDA", "long", "5", "AI", "infrastructure"],
        ticker_already_held=False,
    )
    if err is not None or parsed_new is None:
        raise AssertionError(f"unexpected new-ticker parse: {parsed_new}, {err}")
    if (
        parsed_new.ticker != "NVDA"
        or parsed_new.holding_horizon != "long"
        or parsed_new.shares != 5.0
        or parsed_new.cost_basis is not None
        or parsed_new.reasoning != "AI infrastructure"
    ):
        raise AssertionError(f"unexpected new-ticker parse: {parsed_new}")

    parsed_with_cost, err = parse_strategy_add_args(
        ["NVDA", "long", "5", "150.25", "AI", "infrastructure"],
        ticker_already_held=False,
    )
    if err is not None or parsed_with_cost is None:
        raise AssertionError(f"cost parse failed: {parsed_with_cost}, {err}")
    if parsed_with_cost.cost_basis != 150.25 or parsed_with_cost.reasoning != "AI infrastructure":
        raise AssertionError(f"unexpected cost parse: {parsed_with_cost}")

    parsed_new_default, err = parse_strategy_add_args(
        ["NVDA", "short", "AI", "infrastructure"],
        ticker_already_held=False,
    )
    if err is not None or parsed_new_default is None:
        raise AssertionError(f"unexpected default shares parse: {parsed_new_default}, {err}")
    if parsed_new_default.shares != 1.0 or parsed_new_default.holding_horizon != "short":
        raise AssertionError(f"unexpected default shares parse: {parsed_new_default}")

    parsed_existing, err = parse_strategy_add_args(
        ["9988.HK", "long", "120", "target", "price", "thesis"],
        ticker_already_held=True,
    )
    if err is not None or parsed_existing is None:
        raise AssertionError(f"existing holding parse failed: {err}")
    if (
        parsed_existing.ticker != "9988.HK"
        or parsed_existing.holding_horizon != "long"
        or parsed_existing.shares is not None
        or parsed_existing.reasoning != "120 target price thesis"
    ):
        raise AssertionError(f"existing holding should not parse share count: {parsed_existing}")

    _, err = parse_strategy_add_args(["NVDA", "medium", "thesis"], ticker_already_held=False)
    if err != "add_ticker_strategy_horizon_invalid":
        raise AssertionError(f"invalid horizon should fail: {err}")

    print("Strategy argument parsing checks passed.")


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
