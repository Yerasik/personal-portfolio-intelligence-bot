#!/usr/bin/env python3
"""Smoke tests for the price-move explainer and its alert/analyze wiring."""

from __future__ import annotations

import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scheduler.jobs as jobs_module
from analysis.move_explainer import (
    build_price_move_explanation_prompt,
    explain_price_move,
)
from bot.formatter import format_urgent_alert
from config.settings import RuntimeSettings
from scheduler.jobs import SchedulerServices, run_rule_evaluation_job
from storage.models import (
    AppConfig,
    BotState,
    MarketQuote,
    NewsCache,
    NewsItem,
    Portfolio,
    Position,
)
from storage.paths import resolve_data_paths
from storage.repository import DataRepository

NOW = datetime(2026, 6, 4, 12, 0, tzinfo=UTC)


class FakeLlm:
    """Minimal LlmClient stand-in returning a canned response."""

    def __init__(self, response: str, *, configured: bool = True) -> None:
        self.response = response
        self.is_configured = configured
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_prompt_builder() -> None:
    prompt = build_price_move_explanation_prompt(
        "aapl", "down", 6.5, "today", ["Apple downgraded", "Supply chain warning"]
    )
    for needle in ("Ticker: AAPL", "Direction: down", "6.50%", "today", "Apple downgraded"):
        if needle not in prompt:
            raise AssertionError(f"prompt missing {needle!r}:\n{prompt}")

    empty_prompt = build_price_move_explanation_prompt("MSFT", "up", 3.0, "today", [])
    if "No news was provided" not in empty_prompt:
        raise AssertionError("empty-news prompt should adjust guidance")


def test_helper_success_and_fallback() -> None:
    good_llm = FakeLlm(
        '{"drivers":["Earnings beat","Analyst upgrade"],'
        '"sentiment":"positive","assessment":"Momentum looks constructive."}'
    )
    result = explain_price_move(good_llm, "MSFT", 7.2, "today", ["Earnings beat"])
    if result.source != "llm" or result.direction != "up":
        raise AssertionError(f"unexpected success result: {result}")
    if result.sentiment != "positive" or len(result.drivers) != 2:
        raise AssertionError(f"parsing failed: {result}")
    if "not investment advice" not in result.to_message():
        raise AssertionError("disclaimer missing from message")

    failing_llm = FakeLlm(RuntimeError("boom"))
    fallback = explain_price_move(failing_llm, "AAPL", -6.5, "today", [])
    if fallback.source != "fallback" or fallback.direction != "down":
        raise AssertionError(f"unexpected fallback result: {fallback}")
    if "No explanation available" not in fallback.to_message():
        raise AssertionError("fallback message missing raw-price notice")

    unconfigured = FakeLlm("ignored", configured=False)
    off = explain_price_move(unconfigured, "AAPL", -6.5, "today", [])
    if off.source != "fallback" or unconfigured.prompts:
        raise AssertionError("unconfigured LLM should not be called")


def test_alert_pipeline_attaches_explanation() -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="move-explainer-test-"))
    try:
        paths = resolve_data_paths(temp_dir)
        repository = DataRepository(paths)
        repository.save_config(
            AppConfig(alert_price_change_pct=5.0, enable_llm_summaries=True)
        )
        repository.save_portfolio(Portfolio(positions=[Position(ticker="AAPL", shares=1)]))
        repository.save_state(
            BotState(
                latest_prices={
                    "AAPL": MarketQuote(
                        ticker="AAPL",
                        price=160.0,
                        change_pct=-6.5,
                        volume=1000,
                        company_name="Apple Inc.",
                        sector="Technology",
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
                        title="Apple slides on demand worries",
                        source="Test",
                        url="https://example.com/n1",
                        published_at=NOW,
                        fetched_at=NOW,
                        ticker_tags=["AAPL"],
                        summary="Analysts cut targets.",
                    )
                ],
                updated_at=NOW,
            )
        )

        canned = (
            '{"drivers":["Demand worries","Analyst target cuts"],'
            '"sentiment":"negative","assessment":"Near-term pressure persists."}'
        )

        original_llm = jobs_module.LlmClient
        jobs_module.LlmClient = lambda **_: FakeLlm(canned)  # type: ignore[assignment]
        try:
            services = SchedulerServices(
                repository=repository,
                runtime=RuntimeSettings(
                    telegram_bot_token="token", telegram_chat_id="123"
                ),
            )
            run_rule_evaluation_job(services)
        finally:
            jobs_module.LlmClient = original_llm

        state = repository.load_state()
        price_alerts = [a for a in state.pending_alerts if "AAPL" in a.related_tickers]
        if not price_alerts:
            raise AssertionError("expected a persisted AAPL price alert")

        alert = price_alerts[0]
        if not alert.llm_explanation or "Demand worries" not in alert.llm_explanation:
            raise AssertionError(f"explanation not attached: {alert.llm_explanation}")

        from analysis.rules import AlertCandidate

        candidate = AlertCandidate(
            id=alert.id,
            type="price_drop",
            ticker="AAPL",
            industry=None,
            urgency="urgent",
            title="AAPL down 6.5% today",
            explanation="threshold breached",
            created_at=alert.created_at,
            llm_explanation=alert.llm_explanation,
        )
        message = format_urgent_alert(candidate)
        if "Explanation (likely reasons)" not in message:
            raise AssertionError("alert message missing explanation block")
        if "not investment advice" not in message:
            raise AssertionError("alert message missing disclaimer")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def run_test() -> None:
    test_prompt_builder()
    test_helper_success_and_fallback()
    test_alert_pipeline_attaches_explanation()
    print("Price-move explainer checks passed.")


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
