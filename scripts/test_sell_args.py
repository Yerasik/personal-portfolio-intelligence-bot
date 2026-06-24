#!/usr/bin/env python3
"""Tests for /sell_ticker argument parsing."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.sell_args import is_valid_sell_reasoning, parse_sell_args
from storage.models import Portfolio, Position


def run_test() -> None:
    portfolio = Portfolio(
        positions=[Position(ticker="6082.HK", shares=200.0, cost_basis=56.15)]
    )

    full, err = parse_sell_args(
        ["6082.HK", "150.25", "Taking profits"],
        portfolio,
    )
    if err is not None or full is None:
        raise AssertionError(f"unexpected full sell parse: {full}, {err}")
    if full.shares is not None:
        raise AssertionError("expected sell-all parse")

    partial, err = parse_sell_args(
        ["6082.HK", "5", "190.5", "Trimming position"],
        portfolio,
    )
    if err is not None or partial is None or partial.shares != 5.0:
        raise AssertionError(f"unexpected partial sell parse: {partial}, {err}")

    _, err = parse_sell_args(["6082.HK", "62", "-"], portfolio)
    if err != "sell_ticker_reasoning_invalid":
        raise AssertionError(f"placeholder reasoning should fail: {err}")

    _, err = parse_sell_args(["6082.HK", "62", "profit taking"], portfolio)
    if err is not None:
        raise AssertionError(f"valid 3-arg sell should parse: {err}")

    ambiguous, err = parse_sell_args(["6082.HK", "62", "profit taking"], portfolio)
    if ambiguous is None or "sell_warning_maybe_meant_shares" not in ambiguous.warnings:
        raise AssertionError("expected share-count ambiguity warning")

    if is_valid_sell_reasoning("-"):
        raise AssertionError("dash should not be valid reasoning")

    print("Sell args checks passed.")


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
