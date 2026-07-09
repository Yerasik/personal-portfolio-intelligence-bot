#!/usr/bin/env python3
"""Smoke tests for the what-changed-since-yesterday briefing."""

from __future__ import annotations

import shutil
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.change_briefing import (
    ChangeBriefingContent,
    PnLDriver,
    assemble_change_briefing,
    build_review_queue,
    compute_pl_drivers,
    detect_thesis_breaks,
    filter_new_risks,
    should_skip_change_briefing,
)
from analysis.llm import build_fallback_advisory
from analysis.rules import AlertCandidate
from bot.formatter import format_change_briefing
from config.settings import RuntimeSettings
from storage.models import (
    AppConfig,
    BotState,
    MarketQuote,
    PerformanceHistory,
    Portfolio,
    PortfolioPerformanceSnapshot,
    Position,
    PositionLot,
    PositionPerformancePoint,
    SignalsFile,
    TickerSentimentSignal,
    TickerStrategies,
    TickerStrategy,
)
from storage.paths import resolve_data_paths
from storage.repository import DataRepository
from analysis.llm import LlmClient


def _alert(ticker: str, alert_type: str = "price_drop") -> AlertCandidate:
    return AlertCandidate(
        id="test",
        type=alert_type,  # type: ignore[arg-type]
        ticker=ticker,
        industry=None,
        urgency="warning",
        title=f"{ticker} alert",
        explanation="test",
        created_at=datetime.now(tz=UTC),
        details={"change_pct": -3.0, "threshold": 2.0},
    )


def run_test() -> None:
    now = datetime(2026, 7, 9, 2, 0, tzinfo=UTC)
    prior = now - timedelta(hours=24)
    history = PerformanceHistory(
        snapshots=[
            PortfolioPerformanceSnapshot(
                timestamp=prior,
                total_value=50_000.0,
                total_cost=48_000.0,
                daily_pnl_pct=0.0,
                positions={
                    "MU": PositionPerformancePoint(price=900.0, value=900.0),
                    "VRT": PositionPerformancePoint(price=300.0, value=600.0),
                },
            ),
            PortfolioPerformanceSnapshot(
                timestamp=now,
                total_value=51_200.0,
                total_cost=48_000.0,
                daily_pnl_pct=2.4,
                positions={
                    "MU": PositionPerformancePoint(price=948.0, value=948.0),
                    "VRT": PositionPerformancePoint(price=318.0, value=636.0),
                },
            ),
        ]
    )
    state = BotState(
        latest_prices={
            "MU": MarketQuote(
                ticker="MU",
                price=948.0,
                change_pct=5.0,
                fetched_at=now,
            ),
            "VRT": MarketQuote(
                ticker="VRT",
                price=318.0,
                change_pct=1.0,
                fetched_at=now,
            ),
        }
    )
    daily_pnl, delta, drivers = compute_pl_drivers(history, state)
    if daily_pnl is None or not drivers:
        raise AssertionError("expected P/L drivers from snapshots")
    if abs(delta - 1_200.0) > 0.01:
        raise AssertionError(f"unexpected portfolio delta {delta}")

    fresh = filter_new_risks([_alert("MU")], set())
    if not fresh:
        raise AssertionError("expected fresh alert")
    if filter_new_risks([_alert("MU")], {_alert("MU").alert_key}):
        raise AssertionError("duplicate alert should be filtered")

    portfolio = Portfolio(
        positions=[
            Position(
                ticker="MU",
                lots=[PositionLot(shares=1, cost=900.0, date="2026-07-09")],
            )
        ]
    )
    strategies = {
        "MU": TickerStrategy(
            ticker="MU",
            developer_reasoning="AI memory cycle",
            strategy_text="Long memory thesis",
            holding_horizon="long",
            created_at=now,
            updated_at=now,
        )
    }
    signals = SignalsFile(
        sentiment={
            "MU": TickerSentimentSignal(score=-0.4, article_count=5, updated_at=now),
        }
    )
    breaks = detect_thesis_breaks(
        portfolio,
        strategies,
        state,
        signals,
        [_alert("MU")],
        AppConfig(alert_price_change_pct=2.0),
    )
    if not breaks:
        raise AssertionError("expected thesis break for MU")

    advisory = build_fallback_advisory([_alert("MU")], portfolio)
    queue = build_review_queue([_alert("MU")], advisory, lang="en")
    if not queue:
        raise AssertionError("expected review queue items")

    content = ChangeBriefingContent(
        portfolio_daily_pnl_pct=2.4,
        portfolio_value_delta_hkd=1_200.0,
        pl_drivers=drivers,
        new_risks=fresh,
        thesis_breaks=breaks,
        review_queue=queue,
    )
    message = format_change_briefing(content, lang="en")
    for token in ("What changed since yesterday", "Top P/L drivers", "Recommended review queue"):
        if token not in message:
            raise AssertionError(f"missing section in message: {token}")

    state_sent = BotState(last_change_brief_at=now)
    if not should_skip_change_briefing(
        state_sent,
        now=now + timedelta(hours=1),
        timezone="Asia/Hong_Kong",
    ):
        raise AssertionError("should skip same-day briefing")

    temp_dir = Path(tempfile.mkdtemp(prefix="change-brief-test-"))
    try:
        paths = resolve_data_paths(temp_dir)
        repo = DataRepository(paths)
        repo.save_portfolio(portfolio)
        repo.save_state(state)
        repo.save_performance_history(history)
        repo.save_config(AppConfig(enable_llm_summaries=False))
        repo.save_ticker_strategies(TickerStrategies(by_ticker=strategies))
        repo.save_signals(signals)
        settings = RuntimeSettings(telegram_bot_token="test", telegram_chat_id="1")
        llm = LlmClient(settings=settings, app_config=AppConfig(enable_llm_summaries=False))
        assembled = assemble_change_briefing(repo, llm, language="en", now=now)
        if not assembled.pl_drivers:
            raise AssertionError("assembled briefing missing drivers")
        print("Change briefing checks passed.")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
