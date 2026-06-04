#!/usr/bin/env python3
"""Smoke test for the market data collector."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collectors.market_data import MarketDataService, portfolio_tickers
from storage.models import Portfolio, Position
from storage.paths import resolve_data_paths
from storage.repository import DataRepository


def run_test() -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="market-data-test-"))
    print(f"Using temp data dir: {temp_dir}")

    try:
        paths = resolve_data_paths(temp_dir)
        repository = DataRepository(paths)

        portfolio = Portfolio(
            positions=[
                Position(ticker="AAPL", shares=1),
                Position(ticker="INVALID.TICKER.XYZ", shares=1),
            ]
        )
        repository.save_portfolio(portfolio)

        service = MarketDataService()
        batch = service.run(repository, portfolio)

        print(f"Tickers requested: {portfolio_tickers(portfolio)}")
        print(f"Succeeded: {list(batch.quotes.keys())}")
        print(f"Failed: {batch.failures}")

        state = repository.load_state()
        if state.last_market_fetch_at is None:
            raise AssertionError("last_market_fetch_at was not updated")
        if "AAPL" not in state.latest_prices:
            raise AssertionError("AAPL quote missing from state.latest_prices")

        aapl = state.latest_prices["AAPL"]
        print(
            f"AAPL price={aapl.price} change_pct={aapl.change_pct} "
            f"name={aapl.company_name!r}"
        )
        if aapl.price is None:
            raise AssertionError("AAPL price should not be null")

        if "INVALID.TICKER.XYZ" in state.latest_prices:
            raise AssertionError("failed ticker should not be stored in latest_prices")

        print("state.json snapshot:")
        print(json.dumps(state.model_dump(mode="json"), indent=2))
        print("Market data collector checks passed.")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
