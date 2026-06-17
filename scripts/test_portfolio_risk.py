#!/usr/bin/env python3
"""Smoke tests for portfolio risk estimation."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.portfolio_risk import estimate_portfolio_risk
from analysis.rules import AlertCandidate
from storage.models import (
    AppConfig,
    BotState,
    MarketQuote,
    Portfolio,
    Position,
    SignalsFile,
    TickerSentimentSignal,
)

NOW = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)


def run_test() -> None:
    portfolio = Portfolio(
        positions=[
            Position(ticker="AAPL", shares=10.0, cost_basis=150.0),
            Position(ticker="MSFT", shares=2.0, cost_basis=300.0),
        ]
    )
    state = BotState(
        latest_prices={
            "AAPL": MarketQuote(
                ticker="AAPL",
                price=120.0,
                change_pct=-6.0,
                currency="USD",
                fetched_at=NOW,
            ),
            "MSFT": MarketQuote(
                ticker="MSFT",
                price=310.0,
                change_pct=1.0,
                currency="USD",
                fetched_at=NOW,
            ),
        }
    )
    signals = SignalsFile(
        sentiment={
            "AAPL": TickerSentimentSignal(score=-0.4, updated_at=NOW, article_count=3),
            "MSFT": TickerSentimentSignal(score=0.1, updated_at=NOW, article_count=2),
        }
    )
    alerts = [
        AlertCandidate(
            id="a1",
            type="price_drop",
            ticker="AAPL",
            industry=None,
            urgency="warning",
            title="AAPL down",
            explanation="test",
            created_at=NOW,
        )
    ]

    risk = estimate_portfolio_risk(
        portfolio,
        state,
        signals,
        alerts,
        AppConfig(alert_price_change_pct=5.0),
    )

    if risk.level not in {"moderate", "elevated", "high"}:
        raise AssertionError(f"expected elevated risk, got {risk.level} ({risk.score})")
    if risk.score < 20:
        raise AssertionError(f"risk score too low: {risk.score}")
    if not risk.factors:
        raise AssertionError("expected risk factors")

    print("Portfolio risk checks passed.")


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
