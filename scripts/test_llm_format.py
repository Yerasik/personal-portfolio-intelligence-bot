#!/usr/bin/env python3
"""Smoke tests for LLM text presentation helpers."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.llm_format import format_llm_text


def run_test() -> None:
    raw = (
        "# Portfolio watch\n\n"
        "**Earnings:** Apple reports soon - margins matter - guidance key\n\n"
        "- Review AAPL\n- Monitor sector"
    )
    formatted = format_llm_text(raw)
    if "Portfolio watch" not in formatted:
        raise AssertionError("header text missing")
    if "**" in formatted:
        raise AssertionError("markdown bold should be stripped")
    if "\n\n" not in formatted:
        raise AssertionError("paragraph breaks should be preserved")
    if "• Earnings:" not in formatted and "Earnings:" not in formatted:
        raise AssertionError(f"inline bullets not expanded: {formatted!r}")
    if "• Review AAPL" not in formatted:
        raise AssertionError(f"list bullets missing: {formatted!r}")
    print("LLM format checks passed.")
    print(formatted)


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
