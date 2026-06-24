#!/usr/bin/env python3
"""Tests for /analyze sentiment listing."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.formatter import _format_analyze_sentiment_lines
from storage.models import Portfolio, Position, TickerSentimentSignal

NOW = datetime(2026, 6, 4, 12, 0, tzinfo=UTC)


def run_test() -> None:
    portfolio = Portfolio(
        positions=[
            Position(ticker="AAPL", shares=10),
            Position(ticker="NVDA", shares=5),
            Position(ticker="1810.HK", shares=100),
        ]
    )
    sentiment = {
        "AAPL": TickerSentimentSignal(score=0.25, updated_at=NOW, article_count=3),
        "NVDA": TickerSentimentSignal(score=-0.10, updated_at=NOW, article_count=1),
    }

    lines = _format_analyze_sentiment_lines(portfolio, sentiment, lang="en")
    text = "\n".join(lines)

    if "News sentiment" not in text:
        raise AssertionError("missing sentiment header")
    if text.count("- ") != 3:
        raise AssertionError(f"expected 3 sentiment lines, got:\n{text}")
    if "AAPL: +0.25 (3 article(s))" not in text:
        raise AssertionError(f"AAPL line missing: {text}")
    if "NVDA: -0.10 (1 article(s))" not in text:
        raise AssertionError(f"NVDA line missing: {text}")
    if "1810.HK: n/a (no tagged articles in cache)" not in text:
        raise AssertionError(f"missing holding without sentiment: {text}")

    empty = _format_analyze_sentiment_lines(Portfolio(), sentiment, lang="en")
    if empty:
        raise AssertionError("empty portfolio should produce no sentiment block")

    print("Analyze sentiment listing checks passed.")


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
