#!/usr/bin/env python3
"""Tests for /add_ticker_strategy argument parsing."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.handlers import _parse_strategy_add_args


def run_test() -> None:
    parsed_new = _parse_strategy_add_args(
        ["NVDA", "5", "AI", "infrastructure"],
        ticker_already_held=False,
    )
    if parsed_new != ("NVDA", 5.0, "AI infrastructure"):
        raise AssertionError(f"unexpected new-ticker parse: {parsed_new}")

    parsed_new_default = _parse_strategy_add_args(
        ["NVDA", "AI", "infrastructure"],
        ticker_already_held=False,
    )
    if parsed_new_default != ("NVDA", 1.0, "AI infrastructure"):
        raise AssertionError(f"unexpected default shares parse: {parsed_new_default}")

    parsed_existing = _parse_strategy_add_args(
        ["9988.HK", "120", "target", "price", "thesis"],
        ticker_already_held=True,
    )
    if parsed_existing != (
        "9988.HK",
        None,
        "120 target price thesis",
    ):
        raise AssertionError(f"existing holding should not parse share count: {parsed_existing}")

    print("Strategy argument parsing checks passed.")


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
