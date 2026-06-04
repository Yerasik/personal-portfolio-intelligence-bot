#!/usr/bin/env python3
"""Smoke test for the Ollama integration layer."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.llm import (
    LlmClient,
    build_advisory_prompt,
    build_fallback_advisory,
    parse_advisory_response,
    resolve_ollama_settings,
)
from analysis.rules import AlertCandidate
from config.settings import RuntimeSettings
from storage.models import AppConfig, BotState, MarketQuote, NewsCache, NewsItem, Portfolio, Position

NOW = datetime(2026, 6, 4, 12, 0, tzinfo=UTC)


def _sample_alert() -> AlertCandidate:
    return AlertCandidate(
        id="abc123",
        type="price_drop",
        ticker="AAPL",
        industry=None,
        urgency="warning",
        title="AAPL down 6.5% today",
        explanation="AAPL fell 6.50% since the last market fetch.",
        created_at=NOW,
    )


def test_resolve_settings() -> None:
    class SettingsStub:
        def __init__(self, base: str | None, model: str | None) -> None:
            self.ollama_base_url = base
            self.ollama_model = model

    config = AppConfig(
        ollama_base_url="http://config-ollama:11434",
        ollama_model="config-model",
    )

    env_base, env_model = resolve_ollama_settings(
        SettingsStub("http://env-ollama:11434", "env-model"),
        config,
    )
    if env_base != "http://env-ollama:11434" or env_model != "env-model":
        raise AssertionError("environment settings should take precedence")

    fallback_base, fallback_model = resolve_ollama_settings(
        SettingsStub(None, None),
        config,
    )
    if fallback_base != "http://config-ollama:11434" or fallback_model != "config-model":
        raise AssertionError("config fallback did not apply")


def test_prompt_and_parse() -> None:
    portfolio = Portfolio(positions=[Position(ticker="AAPL", shares=10)])
    config = AppConfig(focus_industries=["Consumer Electronics"])
    state = BotState(
        latest_prices={
            "AAPL": MarketQuote(
                ticker="AAPL",
                price=180.0,
                change_pct=-6.5,
                volume=1000,
                company_name="Apple Inc.",
                fetched_at=NOW,
            )
        }
    )
    news_cache = NewsCache(
        items=[
            NewsItem(
                id="n1",
                title="Apple faces supply chain warning",
                source="Test Feed",
                url="https://news.example.com/n1",
                published_at=NOW,
                fetched_at=NOW,
                ticker_tags=["AAPL"],
                sector_tags=["Consumer Electronics"],
                summary="Apple warned about supply chain pressure.",
            )
        ]
    )
    alerts = [_sample_alert()]
    prompt = build_advisory_prompt(portfolio, config, state, news_cache, alerts)
    if "Apple Inc." not in prompt or "AAPL down 6.5% today" not in prompt:
        raise AssertionError("prompt missing expected context")

    parsed = parse_advisory_response(
        '{"urgency":"warning","summary":"Review AAPL due to price drop.",'
        '"suggested_actions":["review","monitor"]}'
    )
    if parsed.urgency != "warning":
        raise AssertionError("parse_advisory_response failed")


def test_fallback_on_connection_error() -> None:
    settings = RuntimeSettings(
        telegram_bot_token="token",
        telegram_chat_id="chat",
        ollama_base_url="http://ollama:11434",
        ollama_model="llama3.1:8b",
    )
    client = LlmClient(settings=settings, timeout_seconds=1.0)
    portfolio = Portfolio(positions=[Position(ticker="AAPL", shares=1)])
    config = AppConfig()
    state = BotState()
    news_cache = NewsCache()
    alerts = [_sample_alert()]

    def _raise_connection_error(*args, **kwargs):
        raise httpx.ConnectError("connection refused", request=httpx.Request("POST", "http://ollama/api/generate"))

    with patch.object(client, "generate", side_effect=_raise_connection_error):
        result = client.synthesize_advisory(portfolio, config, state, news_cache, alerts)

    if result.source != "fallback":
        raise AssertionError("expected fallback result")
    if "Review AAPL" not in result.suggested_actions:
        raise AssertionError("fallback actions missing review guidance")
    print("Fallback result:")
    print(json.dumps(asdict(result), indent=2, default=str))


def test_successful_ollama_response() -> None:
    settings = RuntimeSettings(
        telegram_bot_token="token",
        telegram_chat_id="chat",
        ollama_base_url="http://ollama:11434",
        ollama_model="llama3.1:8b",
    )
    client = LlmClient(settings=settings)
    portfolio = Portfolio(positions=[Position(ticker="AAPL", shares=1)])
    config = AppConfig()
    state = BotState()
    news_cache = NewsCache()
    alerts = [_sample_alert()]

    mock_response = (
        '{"urgency":"warning","summary":"AAPL moved sharply lower; review the position.",'
        '"suggested_actions":["review","monitor"]}'
    )

    with patch.object(client, "generate", return_value=mock_response):
        result = client.synthesize_advisory(portfolio, config, state, news_cache, alerts)

    if result.source != "ollama":
        raise AssertionError("expected ollama result")
    if result.urgency != "warning":
        raise AssertionError("expected warning urgency from model")
    print("Ollama result:")
    print(json.dumps(asdict(result), indent=2, default=str))


def run_test() -> None:
    test_resolve_settings()
    test_prompt_and_parse()
    test_fallback_on_connection_error()
    test_successful_ollama_response()
    print("LLM integration checks passed.")


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
