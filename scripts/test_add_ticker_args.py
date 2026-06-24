#!/usr/bin/env python3
"""Tests for /add_ticker argument parsing."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.add_ticker_args import parse_add_ticker_args


def run_test() -> None:
    parsed_default, err = parse_add_ticker_args(["AAPL"])
    if err is not None or parsed_default is None:
        raise AssertionError(f"default parse failed: {err}")
    if (
        parsed_default.ticker != "AAPL"
        or parsed_default.shares != 1.0
        or parsed_default.cost_basis is not None
    ):
        raise AssertionError(f"unexpected default parse: {parsed_default}")

    parsed_full, err = parse_add_ticker_args(["1810.HK", "100", "12.5"])
    if err is not None or parsed_full is None:
        raise AssertionError(f"full parse failed: {err}")
    if (
        parsed_full.ticker != "1810.HK"
        or parsed_full.shares != 100.0
        or parsed_full.cost_basis != 12.5
    ):
        raise AssertionError(f"unexpected full parse: {parsed_full}")

    _, err = parse_add_ticker_args(["AAPL", "5", "150", "extra"])
    if err != "add_ticker_usage":
        raise AssertionError(f"extra args should fail: {err}")

    _, err = parse_add_ticker_args(["AAPL", "0"])
    if err != "add_ticker_shares_invalid":
        raise AssertionError(f"zero shares should fail: {err}")

    _, err = parse_add_ticker_args(["AAPL", "5", "-1"])
    if err != "add_ticker_cost_invalid":
        raise AssertionError(f"negative cost should fail: {err}")

    print("Add ticker argument parsing checks passed.")


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
