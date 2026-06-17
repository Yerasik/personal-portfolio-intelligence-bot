#!/usr/bin/env python3
"""Smoke tests for the deep digest scheduler job."""

from __future__ import annotations

import shutil
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.deep_digest import run_deep_digest
from config.settings import RuntimeSettings
from scheduler.jobs import SchedulerServices, run_deep_digest_job
from storage.models import (
    AppConfig,
    BotState,
    BotUser,
    BotUsers,
    MarketQuote,
    NewsCache,
    NewsItem,
    Portfolio,
    Position,
    SignalsFile,
    TickerProsConsMemo,
    TickerSentimentSignal,
)
from storage.paths import resolve_data_paths
from storage.repository import DataRepository

NOW = datetime(2026, 6, 17, 6, 5, tzinfo=UTC)


class FakeLlm:
    def __init__(self, response: str = "MARKET CONTEXT: calm.\nTICKER HIGHLIGHTS:\n- AAPL: steady") -> None:
        self.response = response
        self.prompts: list[str] = []

    @property
    def is_configured(self) -> bool:
        return True

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


class RecordingNotifier:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []
        self.is_configured = True

    def deliver_deep_digest(self, repository: DataRepository, messages_by_language: dict[str, str]) -> bool:
        for user in repository.load_users().users:
            message = messages_by_language.get(user.language) or messages_by_language.get("en", "")
            self.calls.append((user.chat_id, message))
        return bool(self.calls)


def run_test() -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="deep-digest-test-"))
    print(f"Using temp data dir: {temp_dir}")

    try:
        paths = resolve_data_paths(temp_dir)
        repository = DataRepository(paths)
        repository.save_config(
            AppConfig(
                enable_llm_summaries=True,
                deep_digest_times=["06:00", "20:00"],
                enable_deep_digest=True,
            )
        )
        repository.save_portfolio(
            Portfolio(positions=[Position(ticker="AAPL", shares=10)])
        )
        repository.save_users(
            BotUsers(
                users=[
                    BotUser(chat_id=111, language="en", role="ordinary"),
                    BotUser(chat_id=222, language="de", role="developer"),
                ]
            )
        )
        repository.save_state(
            BotState(
                latest_prices={
                    "AAPL": MarketQuote(
                        ticker="AAPL",
                        price=180.0,
                        change_pct=1.5,
                        fetched_at=NOW,
                    )
                },
                deep_digest_price_snapshot={"AAPL": 175.0},
                deep_digest_sentiment_snapshot={"AAPL": 0.10},
            )
        )
        repository.save_signals(
            SignalsFile(
                sentiment={
                    "AAPL": TickerSentimentSignal(
                        score=0.25,
                        updated_at=NOW,
                        article_count=2,
                    )
                },
                pros_cons={
                    "AAPL": TickerProsConsMemo(
                        memo="PROS:\n- Strong demand\nCONS:\n- Valuation",
                        generated_at=NOW,
                        source="llm",
                    )
                },
            )
        )
        ts = NOW - timedelta(hours=2)
        repository.save_news_cache(
            NewsCache(
                items=[
                    NewsItem(
                        id="n1",
                        title="Apple unveils new services bundle",
                        source="Test",
                        url="https://example.com/n1",
                        published_at=ts,
                        fetched_at=ts,
                        ticker_tags=["AAPL"],
                    )
                ]
            )
        )

        llm = FakeLlm()
        notifier = RecordingNotifier()

        runtime = RuntimeSettings(telegram_bot_token="token", telegram_chat_id="12345")
        services = SchedulerServices(repository=repository, runtime=runtime, notifier=notifier)
        services_llm = FakeLlm()
        original_client = __import__("scheduler.jobs", fromlist=["LlmClient"]).LlmClient
        jobs_module = __import__("scheduler.jobs")
        jobs_module.LlmClient = lambda settings, app_config=None: services_llm  # type: ignore[misc]
        try:
            run_deep_digest_job(services)
        finally:
            jobs_module.LlmClient = original_client

        if len(notifier.calls) != 2:
            raise AssertionError("run_deep_digest_job should fan out to all users")

        sent = run_deep_digest(
            repository,
            llm,
            repository.load_config(),
            notifier,
            now=NOW,
            force=True,
        )
        if not sent:
            raise AssertionError("expected deep digest to send")

        if len(notifier.calls) != 4:
            raise AssertionError(f"expected fan-out to 4 sends after forced rerun, got {len(notifier.calls)}")

        chat_ids = {chat_id for chat_id, _message in notifier.calls}
        if chat_ids != {111, 222}:
            raise AssertionError(f"unexpected fan-out chat ids: {chat_ids}")

        if not llm.prompts:
            raise AssertionError("expected Ollama prompt to be generated")

        state = repository.load_state()
        if state.digest_sent_at is None:
            raise AssertionError("digest_sent_at should be written after send")
        if state.deep_digest_price_snapshot.get("AAPL") != 180.0:
            raise AssertionError("price snapshot should update after send")
        if state.deep_digest_sentiment_snapshot.get("AAPL") != 0.25:
            raise AssertionError("sentiment snapshot should update after send")

        duplicate = run_deep_digest(
            repository,
            llm,
            repository.load_config(),
            notifier,
            now=NOW,
        )
        if duplicate:
            raise AssertionError("duplicate send should be skipped without force")
        if len(notifier.calls) != 4:
            raise AssertionError("fan-out should not run again for duplicate slot")

        print("Deep digest checks passed.")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
