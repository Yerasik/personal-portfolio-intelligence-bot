#!/usr/bin/env python3
"""Smoke tests for HKD portfolio valuation."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.portfolio_valuation import (
    build_portfolio_valuation,
    refresh_fx_rates,
    resolve_fx_rates,
)
from storage.models import BotState, MarketQuote, Portfolio, Position
from storage.paths import resolve_data_paths
from storage.repository import DataRepository
from unittest.mock import patch

NOW = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
FX = {"USD": 7.8, "HKD": 1.0, "JPY": 0.052}


def test_cached_fx_rates() -> None:
    state = BotState(fx_rates_to_hkd={"USD": 7.75, "JPY": 0.05})
    rates = resolve_fx_rates(state, fetch_missing=False)
    if rates["USD"] != 7.75 or rates["JPY"] != 0.05:
        raise AssertionError(f"unexpected cached FX rates: {rates}")
    print("Cached FX resolution: ok")


def test_refresh_fx_rates_persists_state() -> None:
    import tempfile

    temp_dir = Path(tempfile.mkdtemp(prefix="fx-refresh-test-"))
    repository = DataRepository(resolve_data_paths(temp_dir))
    portfolio = Portfolio(positions=[Position(ticker="VRT", shares=1.0)], cash_usd=100.0)

    with patch(
        "analysis.portfolio_valuation.fetch_fx_rates_to_hkd",
        return_value={"USD": 7.81, "JPY": 0.051},
    ):
        rates = refresh_fx_rates(repository, portfolio)

    state = repository.load_state()
    if state.last_fx_fetch_at is None:
        raise AssertionError("last_fx_fetch_at was not set")
    if state.fx_rates_to_hkd.get("USD") != 7.81:
        raise AssertionError(f"USD rate not persisted: {state.fx_rates_to_hkd}")
    if rates.get("USD") != 7.81:
        raise AssertionError(f"refresh return mismatch: {rates}")
    print("FX refresh persistence: ok")


def run_test() -> None:
    test_cached_fx_rates()
    test_refresh_fx_rates_persists_state()
    portfolio = Portfolio(
        positions=[
            Position(ticker="VRT", shares=3.0, cost_basis=318.2),
            Position(ticker="1810.HK", shares=201.0, cost_basis=31.81),
        ]
    )
    state = BotState(
        latest_prices={
            "VRT": MarketQuote(
                ticker="VRT",
                price=310.0,
                change_pct=1.0,
                currency="USD",
                fetched_at=NOW,
            ),
            "1810.HK": MarketQuote(
                ticker="1810.HK",
                price=26.0,
                change_pct=-1.0,
                currency="HKD",
                fetched_at=NOW,
            ),
        }
    )

    valuation = build_portfolio_valuation(portfolio, state, fx_rates=FX)
    vrt = next(item for item in valuation.positions if item.ticker == "VRT")
    hk = next(item for item in valuation.positions if item.ticker == "1810.HK")

    expected_vrt_value = 310.0 * 3.0 * 7.8
    expected_hk_value = 26.0 * 201.0
    if abs((vrt.market_value_hkd or 0) - expected_vrt_value) > 0.01:
        raise AssertionError(f"VRT HKD value wrong: {vrt.market_value_hkd}")

    if abs((hk.market_value_hkd or 0) - expected_hk_value) > 0.01:
        raise AssertionError(f"1810.HK HKD value wrong: {hk.market_value_hkd}")

    total = expected_vrt_value + expected_hk_value
    if abs(valuation.total_market_value_hkd - total) > 0.01:
        raise AssertionError("total market value wrong")

    if vrt.weight_pct is None or hk.weight_pct is None:
        raise AssertionError("weights should be set")
    if abs(vrt.weight_pct + hk.weight_pct - 100.0) > 0.1:
        raise AssertionError("weights should sum to ~100")

    if vrt.pl_hkd is None or hk.pl_hkd is None:
        raise AssertionError("P/L should be computed when cost basis exists")

    print("Portfolio valuation checks passed.")


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
