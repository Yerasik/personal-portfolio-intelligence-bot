#!/usr/bin/env python3
"""Smoke test for the market data collector."""

from __future__ import annotations

import json
import logging
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collectors import market_data as market_data_module
from collectors.market_data import MarketDataService, fetch_quote, portfolio_tickers
from storage.models import MarketQuote, Portfolio, Position
from storage.paths import resolve_data_paths
from storage.repository import DataRepository

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")


def _fetch_quote_or_fail(ticker: str, fetched_at: datetime | None = None) -> MarketQuote:
    """Call the real fetcher, but simulate a bad ticker without hitting Yahoo."""
    if ticker == "ZZZZ.INVALID":
        raise ValueError(f"Unknown or delisted ticker: {ticker}")
    return fetch_quote(ticker, fetched_at=fetched_at)


def run_test() -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="market-data-test-"))
    print(f"Using temp data dir: {temp_dir}")

    try:
        paths = resolve_data_paths(temp_dir)
        repository = DataRepository(paths)

        portfolio = Portfolio(
            positions=[
                Position(ticker="AAPL", shares=1),
                Position(ticker="ZZZZ.INVALID", shares=1),
            ]
        )
        repository.save_portfolio(portfolio)

        service = MarketDataService()
        fx_patch = {"USD": 7.82, "JPY": 0.051}
        with (
            patch.object(market_data_module, "fetch_quote", side_effect=_fetch_quote_or_fail),
            patch(
                "analysis.portfolio_valuation.refresh_fx_rates",
                return_value=fx_patch,
            ) as refresh_fx,
        ):
            batch = service.run(repository, portfolio)

        print(f"Tickers requested: {portfolio_tickers(portfolio)}")
        print(f"Succeeded: {list(batch.quotes.keys())}")
        print(f"Failed: {batch.failures}")

        state = repository.load_state()
        if state.last_market_fetch_at is None:
            raise AssertionError("last_market_fetch_at was not updated")
        if "AAPL" not in state.latest_prices:
            raise AssertionError("AAPL quote missing from state.latest_prices")
        if not refresh_fx.called:
            raise AssertionError("refresh_fx_rates should run after market fetch")

        aapl = state.latest_prices["AAPL"]
        print(
            f"AAPL price={aapl.price} change_pct={aapl.change_pct} "
            f"name={aapl.company_name!r}"
        )
        if aapl.price is None:
            raise AssertionError("AAPL price should not be null")

        if batch.failures != {"ZZZZ.INVALID": "Unknown or delisted ticker: ZZZZ.INVALID"}:
            raise AssertionError(f"unexpected failures map: {batch.failures}")

        if "ZZZZ.INVALID" in state.latest_prices:
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
