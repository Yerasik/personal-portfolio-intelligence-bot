#!/usr/bin/env python3
"""Smoke tests for portfolio industry inference."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.industries import (
    build_news_focus_industries,
    guess_industry_with_llm,
    infer_industries_from_portfolio,
)
from storage.models import Portfolio, Position


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

    print("Industry inference checks passed.")


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
