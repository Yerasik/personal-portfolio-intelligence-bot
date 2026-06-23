#!/usr/bin/env python3
"""Smoke tests for portfolio add/remove helpers."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from storage.models import Portfolio, Position
from storage.paths import resolve_data_paths
from storage.portfolio_ops import (
    add_ticker_to_portfolio,
    normalize_ticker,
    remove_ticker_from_portfolio,
    sell_ticker_from_portfolio,
    validate_ticker_format,
)
from storage.repository import DataRepository


def run_test() -> None:
    assert normalize_ticker(" aapl ") == "AAPL"
    assert validate_ticker_format("1810.HK") is None
    assert validate_ticker_format("") is not None
    assert validate_ticker_format("bad ticker") is not None

    portfolio = Portfolio(
        positions=[Position(ticker="AAPL", shares=10, cost_basis=150.0)]
    )
    updated, duplicate = add_ticker_to_portfolio(portfolio, "AAPL", shares=3)
    if not duplicate.success:
        raise AssertionError(f"increment existing should succeed: {duplicate}")
    aapl = next(p for p in updated.positions if p.ticker == "AAPL")
    if aapl.shares != 13:
        raise AssertionError(f"expected 13 AAPL shares, got {aapl.shares}")

    updated, added = add_ticker_to_portfolio(updated, "NVDA", shares=5)
    if not added.success or len(updated.positions) != 2:
        raise AssertionError(f"add failed: {added}")

    updated, missing = remove_ticker_from_portfolio(updated, "TSLA")
    if missing.success:
        raise AssertionError("remove missing ticker should fail")

    updated, removed = remove_ticker_from_portfolio(updated, "AAPL")
    if not removed.success or len(updated.positions) != 1:
        raise AssertionError(f"remove failed: {removed}")

    portfolio = Portfolio(
        positions=[Position(ticker="MSFT", shares=10, cost_basis=400.0)],
        cash=1000.0,
    )
    updated, sold = sell_ticker_from_portfolio(
        portfolio,
        "MSFT",
        sell_price=420.0,
        shares=4.0,
    )
    if not sold.success or sold.proceeds != 1680.0:
        raise AssertionError(f"partial sell failed: {sold}")
    if updated.cash != 2680.0:
        raise AssertionError(f"unexpected cash after partial sell: {updated.cash}")
    msft = next(p for p in updated.positions if p.ticker == "MSFT")
    if msft.shares != 6:
        raise AssertionError(f"expected 6 MSFT shares, got {msft.shares}")

    updated, sold_all = sell_ticker_from_portfolio(updated, "MSFT", sell_price=425.0)
    if not sold_all.success or not sold_all.fully_sold:
        raise AssertionError(f"full sell failed: {sold_all}")
    if updated.positions:
        raise AssertionError("position should be removed after full sell")
    if updated.cash != 5230.0:
        raise AssertionError(f"unexpected cash after full sell: {updated.cash}")

    temp_dir = Path(tempfile.mkdtemp(prefix="portfolio-edit-test-"))
    try:
        paths = resolve_data_paths(temp_dir)
        repo = DataRepository(paths)
        repo.save_portfolio(Portfolio(positions=[Position(ticker="MSFT", shares=2)]))

        with patch(
            "storage.portfolio_ops.verify_ticker_exists",
            return_value=None,
        ):
            result = repo.add_ticker_to_portfolio("GOOG", shares=3)
        if not result.success:
            raise AssertionError(f"repository add failed: {result.message}")

        loaded = repo.load_portfolio()
        tickers = {position.ticker for position in loaded.positions}
        if tickers != {"MSFT", "GOOG"}:
            raise AssertionError(f"unexpected tickers after add: {tickers}")

        removed_repo = repo.remove_ticker_from_portfolio("MSFT")
        if not removed_repo.success:
            raise AssertionError(f"repository remove failed: {removed_repo.message}")

        loaded = repo.load_portfolio()
        if [position.ticker for position in loaded.positions] != ["GOOG"]:
            raise AssertionError("remove did not persist")

        print("Portfolio edit checks passed.")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
