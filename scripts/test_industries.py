#!/usr/bin/env python3
"""Smoke tests for portfolio industry inference."""

from __future__ import annotations

import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.industries import (
    build_news_focus_industries,
    guess_industry_with_llm,
    industry_label_from_quote,
    infer_industries_from_portfolio,
    seed_ticker_industry_if_missing,
)
from storage.models import BotState, MarketQuote, Portfolio, Position, TickerIndustryMap
from storage.paths import resolve_data_paths
from storage.repository import DataRepository


class FakeLlm:
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


def run_test() -> None:
    portfolio = Portfolio(
        positions=[
            Position(ticker="aapl", shares=1),
            Position(ticker="MSFT", shares=2),
            Position(ticker="UNKNOWN", shares=3),
            Position(ticker="AAPL", shares=4),
        ]
    )
    mapping = {
        "AAPL": " Consumer Electronics ",
        "msft": "Software - Infrastructure",
        "EMPTY": "",
    }

    industries = infer_industries_from_portfolio(portfolio, mapping)
    expected = {"Consumer Electronics", "Software - Infrastructure"}
    if industries != expected:
        raise AssertionError(f"unexpected industries: {industries}")

    combined = build_news_focus_industries(
        ["AI", "consumer electronics"],
        portfolio,
        mapping,
    )
    if combined != ["AI", "consumer electronics", "Software - Infrastructure"]:
        raise AssertionError(f"unexpected combined industries: {combined}")

    empty = infer_industries_from_portfolio(Portfolio(), mapping)
    if empty:
        raise AssertionError(f"empty portfolio should infer no industries: {empty}")

    llm = FakeLlm(" Semiconductor   Manufacturing ")
    guessed = guess_industry_with_llm(llm, " nvda ", "NVIDIA Corporation")
    if guessed != "Semiconductor Manufacturing":
        raise AssertionError(f"unexpected LLM industry guess: {guessed}")
    if "Ticker: NVDA" not in llm.prompts[0]:
        raise AssertionError(f"ticker was not normalized in prompt: {llm.prompts[0]}")

    unknown_guess = guess_industry_with_llm(FakeLlm("UNKNOWN"), "????")
    if unknown_guess is not None:
        raise AssertionError(f"UNKNOWN response should return None: {unknown_guess}")

    class FailingLlm:
        def generate(self, prompt: str) -> str:
            raise RuntimeError("ollama unavailable")

    failed_guess = guess_industry_with_llm(FailingLlm(), "AAPL")
    if failed_guess is not None:
        raise AssertionError(f"LLM failure should return None: {failed_guess}")

    quote = MarketQuote(
        ticker="VRT",
        price=100.0,
        industry="Electrical Equipment & Parts",
        sector="Industrials",
        currency="USD",
        fetched_at=datetime.now(timezone.utc),
    )
    if industry_label_from_quote(quote) != "Electrical Equipment & Parts":
        raise AssertionError("expected industry over sector from quote")

    temp_dir = Path(tempfile.mkdtemp(prefix="industry-seed-test-"))
    try:
        repo = DataRepository(resolve_data_paths(temp_dir))
        repo.save_ticker_industries(TickerIndustryMap())
        repo.save_state(BotState(latest_prices={"VRT": quote}))
        seeded = seed_ticker_industry_if_missing(repo, "VRT")
        if seeded != "Electrical Equipment & Parts":
            raise AssertionError(f"unexpected seeded label: {seeded}")
        loaded = repo.load_ticker_industries()
        if loaded.ticker_to_industry.get("VRT") != "Electrical Equipment & Parts":
            raise AssertionError("seed was not persisted")

        again = seed_ticker_industry_if_missing(repo, "VRT")
        if again is not None:
            raise AssertionError("existing mapping should not be overwritten")

        manual = repo.load_ticker_industries()
        manual = manual.model_copy(
            update={
                "ticker_to_industry": {
                    **manual.ticker_to_industry,
                    "NVDA": "US Semiconductors",
                }
            }
        )
        repo.save_ticker_industries(manual)
        nvda_quote = MarketQuote(
            ticker="NVDA",
            price=100.0,
            industry="Semiconductors",
            fetched_at=datetime.now(timezone.utc),
        )
        if seed_ticker_industry_if_missing(repo, "NVDA", quote=nvda_quote) is not None:
            raise AssertionError("manual NVDA mapping should be preserved")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    print("Industry inference checks passed.")


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
