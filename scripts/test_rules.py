#!/usr/bin/env python3
"""Smoke test for the rule-based analysis engine."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.rules import AlertCandidate, RulesEngine
from storage.models import (
    AppConfig,
    BotState,
    EvaluatedAlertRecord,
    MarketQuote,
    NewsCache,
    NewsItem,
    Portfolio,
    Position,
    SentAlertRecord,
)

NOW = datetime(2026, 6, 4, 12, 0, tzinfo=UTC)


def _news_item(
    *,
    item_id: str,
    title: str,
    tickers: list[str] | None = None,
    sectors: list[str] | None = None,
    hours_ago: int = 1,
) -> NewsItem:
    timestamp = NOW - timedelta(hours=hours_ago)
    return NewsItem(
        id=item_id,
        title=title,
        source="Test Feed",
        url=f"https://news.example.com/{item_id}",
        published_at=timestamp,
        fetched_at=timestamp,
        ticker_tags=tickers or [],
        sector_tags=sectors or [],
        summary=title,
    )


def _assert_alerts(
    alerts: list[AlertCandidate],
    expected_types: set[str],
    label: str,
) -> None:
    found = {alert.type for alert in alerts}
    if found != expected_types:
        raise AssertionError(f"{label}: expected {expected_types}, got {found}")


def run_test() -> None:
    config = AppConfig(
        alert_price_change_pct=5.0,
        alert_negative_news_count=3,
        alert_sector_article_count=3,
        focus_industries=["Consumer Electronics"],
        alert_suppression_hours=12,
        enable_sector_attention_alerts=True,
    )
    engine = RulesEngine(
        app_config=config,
        ticker_to_industry={"AAPL": "Consumer Electronics"},
    )
    portfolio = Portfolio(
        positions=[
            Position(ticker="AAPL", shares=10),
            Position(ticker="MSFT", shares=5),
        ]
    )

    state = BotState(
        latest_prices={
            "AAPL": MarketQuote(
                ticker="AAPL",
                price=180.0,
                change_pct=-6.5,
                volume=1000,
                company_name="Apple Inc.",
                fetched_at=NOW,
            ),
            "MSFT": MarketQuote(
                ticker="MSFT",
                price=420.0,
                change_pct=7.2,
                volume=1000,
                company_name="Microsoft Corp.",
                fetched_at=NOW,
            ),
            "OLD": MarketQuote(
                ticker="OLD",
                price=10.0,
                change_pct=-20.0,
                volume=100,
                company_name="Removed Holding Inc.",
                fetched_at=NOW,
            ),
        }
    )

    news_cache = NewsCache(
        items=[
            _news_item(
                item_id="n1",
                title="Apple shares fall after downgrade",
                tickers=["AAPL"],
                hours_ago=2,
            ),
            _news_item(
                item_id="n2",
                title="Apple faces lawsuit over product recall",
                tickers=["AAPL"],
                hours_ago=3,
            ),
            _news_item(
                item_id="n3",
                title="Apple warns on supply chain slump",
                tickers=["AAPL"],
                hours_ago=4,
            ),
            _news_item(
                item_id="s1",
                title="Consumer Electronics demand update",
                sectors=["Consumer Electronics"],
                tickers=["AAPL"],
                hours_ago=1,
            ),
            _news_item(
                item_id="s2",
                title="Gadget makers face margin pressure",
                sectors=["Consumer Electronics"],
                tickers=["AAPL"],
                hours_ago=2,
            ),
            _news_item(
                item_id="s3",
                title="Wearables market outlook shifts",
                sectors=["Consumer Electronics"],
                tickers=["AAPL"],
                hours_ago=3,
            ),
        ]
    )

    alerts = engine.evaluate(portfolio, state, news_cache, now=NOW)
    _assert_alerts(
        alerts,
        {"price_drop", "price_rise", "repeated_negative_news", "sector_attention"},
        "combined rules",
    )
    if any(alert.ticker == "OLD" for alert in alerts):
        raise AssertionError("stale latest_prices entry OLD should not trigger alerts")

    suppressed_state = state.model_copy(
        update={
            "last_sent_alerts": [
                SentAlertRecord(
                    alert_key="price_drop:AAPL:",
                    alert_id="existing",
                    sent_at=NOW - timedelta(hours=1),
                )
            ]
        }
    )
    suppressed = engine.evaluate(portfolio, suppressed_state, news_cache, now=NOW)
    if any(alert.type == "price_drop" and alert.ticker == "AAPL" for alert in suppressed):
        raise AssertionError("duplicate price_drop alert for AAPL should be suppressed")

    evaluated_state = state.model_copy(
        update={
            "last_evaluated_alerts": [
                EvaluatedAlertRecord(
                    alert_key="price_rise:MSFT:",
                    evaluated_at=NOW - timedelta(hours=1),
                )
            ]
        }
    )
    evaluated_suppressed = engine.evaluate(
        portfolio, evaluated_state, news_cache, now=NOW
    )
    if any(
        alert.type == "price_rise" and alert.ticker == "MSFT"
        for alert in evaluated_suppressed
    ):
        raise AssertionError(
            "recently evaluated price_rise alert for MSFT should be suppressed"
        )

    portfolio_only_config = AppConfig(
        alert_sector_article_count=3,
        enable_sector_attention_alerts=True,
        focus_industries=["AI"],
    )
    portfolio_only_engine = RulesEngine(
        app_config=portfolio_only_config,
        ticker_to_industry={"AAPL": "Consumer Electronics"},
    )
    portfolio_only_alerts = portfolio_only_engine.evaluate(
        portfolio, state, news_cache, now=NOW
    )
    if not any(
        alert.type == "sector_attention"
        and alert.industry == "Consumer Electronics"
        for alert in portfolio_only_alerts
    ):
        raise AssertionError(
            "portfolio-derived Consumer Electronics should trigger sector alerts"
        )

    ai_news_cache = NewsCache(
        items=[
            _news_item(item_id="ai1", title="AI stocks rally", sectors=["AI"], hours_ago=1),
            _news_item(item_id="ai2", title="AI chip demand surges", sectors=["AI"], hours_ago=2),
            _news_item(item_id="ai3", title="AI data center boom", sectors=["AI"], hours_ago=3),
        ]
    )
    ai_engine = RulesEngine(
        app_config=AppConfig(
            alert_sector_article_count=3,
            focus_industries=["AI"],
            enable_sector_attention_alerts=False,
        ),
        ticker_to_industry={"AAPL": "Consumer Electronics"},
    )
    ai_alerts = ai_engine.evaluate(portfolio, state, ai_news_cache, now=NOW)
    if any(alert.type == "sector_attention" for alert in ai_alerts):
        raise AssertionError("broad AI sector news must not alert when sector alerts are disabled")

    print("Example alert objects:")
    print(json.dumps([asdict(alert) for alert in alerts], indent=2, default=str))
    print("Rules engine checks passed.")


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
