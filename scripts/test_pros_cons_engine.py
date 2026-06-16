#!/usr/bin/env python3
"""Smoke tests for the pros/cons engine."""

from __future__ import annotations

import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.pros_cons_engine import ProsConsEngine
from storage.models import (
    AppConfig,
    BotState,
    MarketQuote,
    NewsCache,
    NewsItem,
    Portfolio,
    Position,
    SignalsFile,
    TickerSentimentSignal,
)
from storage.paths import resolve_data_paths
from storage.repository import DataRepository

NOW = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
FIXED_MEMO = (
    "PROS:\n"
    "- Strong demand\n"
    "- Record profit\n\n"
    "CONS:\n"
    "- Valuation risk\n"
    "- Macro headwinds\n\n"
    "SHORT-TERM OUTLOOK (1–5 days): Momentum may continue."
)


def run_test() -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="pros-cons-test-"))
    try:
        repository = DataRepository(resolve_data_paths(temp_dir))
        repository.save_config(AppConfig(enable_llm_summaries=True))
        repository.save_portfolio(
            Portfolio(positions=[Position(ticker="AAPL", shares=10.0)])
        )
        repository.save_state(
            BotState(
                latest_prices={
                    "AAPL": MarketQuote(
                        ticker="AAPL",
                        price=180.0,
                        change_pct=2.5,
                        company_name="Apple Inc.",
                        fetched_at=NOW,
                    )
                }
            )
        )
        repository.save_news_cache(
            NewsCache(
                items=[
                    NewsItem(
                        id="n1",
                        title="Apple beat profit estimates",
                        source="Test",
                        url="https://example.com/n1",
                        fetched_at=NOW,
                        ticker_tags=["AAPL"],
                    )
                ],
                updated_at=NOW,
            )
        )
        repository.save_signals(
            SignalsFile(
                sentiment={
                    "AAPL": TickerSentimentSignal(
                        score=0.4,
                        updated_at=NOW,
                        article_count=1,
                    )
                }
            )
        )

        llm = MagicMock()
        llm.is_configured = True
        llm.generate.return_value = FIXED_MEMO

        engine = ProsConsEngine(llm, AppConfig(enable_llm_summaries=True))
        result = engine.generate_for_ticker("AAPL", repository=repository)

        if result.memo != FIXED_MEMO:
            raise AssertionError("expected mocked LLM memo")
        if result.source != "llm":
            raise AssertionError("expected llm source")
        if not llm.generate.called:
            raise AssertionError("expected existing Ollama client generate() to be called")

        signals = repository.load_signals()
        stored = signals.pros_cons.get("AAPL")
        if stored is None or stored.memo != FIXED_MEMO:
            raise AssertionError("signals.json pros_cons entry was not persisted")
        if stored.source != "llm":
            raise AssertionError("expected persisted source=llm")

        print("Pros/cons engine checks passed.")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
