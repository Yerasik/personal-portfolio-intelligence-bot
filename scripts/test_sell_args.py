#!/usr/bin/env python3
"""Tests for /sell_ticker argument parsing."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.handlers import _parse_sell_args


def run_test() -> None:
    full = _parse_sell_args(["NVDA", "150.25", "Taking profits"])
    if full != ("NVDA", None, 150.25, "Taking profits"):
        raise AssertionError(f"unexpected full sell parse: {full}")

    partial = _parse_sell_args(["AAPL", "5", "190.5", "Trimming position"])
    if partial != ("AAPL", 5.0, 190.5, "Trimming position"):
        raise AssertionError(f"unexpected partial sell parse: {partial}")

    if _parse_sell_args(["NVDA", "bad", "reason"]) is not None:
        raise AssertionError("invalid price should fail")
    if _parse_sell_args(["NVDA"]) is not None:
        raise AssertionError("too few args should fail")

    print("Sell args checks passed.")


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
