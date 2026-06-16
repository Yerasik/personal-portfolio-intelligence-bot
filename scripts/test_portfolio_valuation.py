#!/usr/bin/env python3
"""Smoke tests for HKD portfolio valuation."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.portfolio_valuation import build_portfolio_valuation
from storage.models import BotState, MarketQuote, Portfolio, Position

NOW = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
FX = {"USD": 7.8, "HKD": 1.0}


def run_test() -> None:
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
