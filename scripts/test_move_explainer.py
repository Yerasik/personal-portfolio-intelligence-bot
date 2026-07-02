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
    AnalyzeTickerContext,
    build_analyze_ticker_prompt,
    build_price_move_explanation_prompt,
    explain_price_move,
    explain_ticker_for_analyze,
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


def test_analyze_ticker_prompt() -> None:
    prompt = build_analyze_ticker_prompt(
        AnalyzeTickerContext(
            ticker="AAPL",
            price=190.25,
            change_pct=-2.4,
            week_52_low=164.0,
            week_52_high=220.5,
            cost_basis=175.0,
            pnl_pct=8.7,
            rsi=58.3,
            headlines=["Apple faces demand headwinds", "Services revenue beats"],
            language="en",
        )
    )
    for needle in (
        "System: You are a concise financial analyst",
        "Respond in English",
        "Ticker: AAPL",
        "Current price: 190.25",
        "Change today: -2.40%",
        "52-week range: 164.00 - 220.50",
        "Cost basis: 175.00",
        "Unrealized P&L: +8.70%",
        "RSI(14): 58.30",
        "1. Apple faces demand headwinds",
        "3 bullet points",
        "actionable observation",
    ):
        if needle not in prompt:
            raise AssertionError(f"analyze prompt missing {needle!r}:\n{prompt}")


def test_analyze_ticker_helper() -> None:
    good_llm = FakeLlm(
        "- Demand concerns weighed on the stock.\n"
        "- Services growth partially offset hardware softness.\n"
        "- RSI remains neutral, suggesting no extreme positioning.\n"
        "Watch the next product-cycle commentary before reassessing exposure."
    )
    context = AnalyzeTickerContext(
        ticker="AAPL",
        price=190.0,
        change_pct=-2.0,
        week_52_low=164.0,
        week_52_high=220.0,
        cost_basis=None,
        pnl_pct=None,
        rsi=55.0,
        headlines=["Apple faces demand headwinds"],
        language="en",
    )
    result = explain_ticker_for_analyze(good_llm, context, window="today")
    if result.source != "llm" or len(result.drivers) != 3:
        raise AssertionError(f"unexpected analyze result: {result}")
    if not result.assessment:
        raise AssertionError("expected closing actionable observation")
    if "concise financial analyst" not in good_llm.prompts[0]:
        raise AssertionError("analyze path should use the new prompt template")


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


def test_alert_pipeline_and_delivery_explanation() -> None:
    """Rule evaluation persists alerts without LLM text; delivery adds explanations."""
    from unittest.mock import patch

    from analysis.rules import AlertCandidate
    from storage.models import BotUser, BotUsers

    temp_dir = Path(tempfile.mkdtemp(prefix="move-explainer-test-"))
    try:
        paths = resolve_data_paths(temp_dir)
        repository = DataRepository(paths)
        repository.save_config(
            AppConfig(alert_price_change_pct=5.0, enable_llm_summaries=True)
        )
        repository.save_portfolio(Portfolio(positions=[Position(ticker="AAPL", shares=1)]))
        repository.save_users(
            BotUsers(users=[BotUser(chat_id=111, language="en", role="developer")])
        )
        repository.save_state(
            BotState(
                latest_prices={
                    "AAPL": MarketQuote(
                        ticker="AAPL",
                        price=160.0,
                        change_pct=-11.0,
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
        fake_llm = FakeLlm(canned)

        original_llm = jobs_module.LlmClient
        jobs_module.LlmClient = lambda **_: fake_llm  # type: ignore[assignment]
        try:
            services = SchedulerServices(
                repository=repository,
                runtime=RuntimeSettings(
                    telegram_bot_token="token", telegram_chat_id="123"
                ),
            )
            with patch("bot.notifier.httpx.Client") as mock_client_cls:
                mock_client = mock_client_cls.return_value
                mock_client.__enter__.return_value = mock_client

                class Response:
                    def raise_for_status(self) -> None:
                        return None

                    def json(self) -> dict:
                        return {"ok": True}

                mock_client.post.return_value = Response()
                run_rule_evaluation_job(services)
        finally:
            jobs_module.LlmClient = original_llm

        state = repository.load_state()
        price_alerts = [a for a in state.pending_alerts if "AAPL" in a.related_tickers]
        if not price_alerts:
            raise AssertionError("expected a persisted AAPL price alert")
        if price_alerts[0].llm_explanation:
            raise AssertionError("LLM explanation should be generated at delivery, not evaluation")

        if not fake_llm.prompts:
            raise AssertionError("delivery should call the LLM for price-move alerts")

        alert = price_alerts[0]
        candidate = AlertCandidate(
            id=alert.id,
            type="price_drop",
            ticker="AAPL",
            industry=None,
            urgency="urgent",
            title="AAPL down 11.0% today",
            explanation="threshold breached",
            created_at=alert.created_at,
        )
        explanation = explain_price_move(
            fake_llm, "AAPL", -11.0, "today", ["Apple slides on demand worries"]
        ).to_message("en")
        message = format_urgent_alert(candidate, llm_explanation=explanation)
        if "Explanation (likely reasons)" not in message:
            raise AssertionError("alert message missing explanation block")
        if "Demand worries" not in message:
            raise AssertionError("alert message missing LLM drivers")
        if "not investment advice" not in message:
            raise AssertionError("alert message missing disclaimer")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def run_test() -> None:
    test_analyze_ticker_prompt()
    test_analyze_ticker_helper()
    test_prompt_builder()
    test_helper_success_and_fallback()
    test_alert_pipeline_and_delivery_explanation()
    print("Price-move explainer checks passed.")


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
