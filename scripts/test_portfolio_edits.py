#!/usr/bin/env python3
"""Smoke tests for portfolio add/remove helpers."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from storage.models import Portfolio, Position, PositionLot
from storage.paths import resolve_data_paths
from storage.portfolio_ops import (
    add_ticker_to_portfolio,
    deposit_cash_to_portfolio,
    normalize_ticker,
    remove_ticker_from_portfolio,
    sell_ticker_from_portfolio,
    validate_ticker_format,
)
from storage.repository import DataRepository

_FX_PATCH = patch(
    "analysis.portfolio_valuation.fetch_fx_rates_to_hkd",
    return_value={"USD": 7.85, "HKD": 1.0},
)


def run_test() -> None:
    assert normalize_ticker(" aapl ") == "AAPL"
    assert validate_ticker_format("1810.HK") is None
    assert validate_ticker_format("") is not None
    assert validate_ticker_format("bad ticker") is not None

    legacy = Position.model_validate(
        {"ticker": "AAPL", "shares": 10, "cost_basis": 150.0, "notes": ""}
    )
    if len(legacy.lots) != 1 or legacy.lots[0].cost != 150.0:
        raise AssertionError("legacy position should migrate to one lot")
    if legacy.lots[0].date != "unknown":
        raise AssertionError("legacy lot date should be unknown")
    if legacy.blended_cost_basis != 150.0:
        raise AssertionError("blended cost should match migrated lot")

    portfolio = Portfolio(positions=[legacy], cash_usd=10_000.0)
    updated, duplicate = add_ticker_to_portfolio(portfolio, "AAPL", shares=3)
    if not duplicate.success:
        raise AssertionError(f"increment existing should succeed: {duplicate}")
    aapl = next(p for p in updated.positions if p.ticker == "AAPL")
    if aapl.shares != 13:
        raise AssertionError(f"expected 13 AAPL shares, got {aapl.shares}")
    if len(aapl.lots) != 2:
        raise AssertionError(f"expected 2 lots after add, got {len(aapl.lots)}")
    if aapl.blended_cost_basis != 150.0:
        raise AssertionError("blended cost should stay 150 when new lot has no cost")

    updated, added_lot = add_ticker_to_portfolio(
        updated,
        "AAPL",
        shares=2,
        cost_basis=200.0,
    )
    if not added_lot.success:
        raise AssertionError(f"lot add should succeed: {added_lot}")
    aapl = next(p for p in updated.positions if p.ticker == "AAPL")
    if len(aapl.lots) != 3:
        raise AssertionError(f"expected 3 lots, got {len(aapl.lots)}")
    expected_cost = (10 * 150.0 + 2 * 200.0) / 12
    if abs(aapl.blended_cost_basis - expected_cost) > 1e-9:
        raise AssertionError(
            f"unexpected blended cost {aapl.blended_cost_basis}, want {expected_cost}"
        )

    updated, added = add_ticker_to_portfolio(updated, "NVDA", shares=5, cost_basis=120.0)
    if not added.success or len(updated.positions) != 2:
        raise AssertionError(f"add failed: {added}")
    expected_usd = 10_000.0 - 2 * 200.0 - 5 * 120.0
    if abs(updated.cash_usd - expected_usd) > 1e-9:
        raise AssertionError(f"expected USD cash {expected_usd}, got {updated.cash_usd}")
    if "debited" not in added.message.lower():
        raise AssertionError(f"add message should mention cash debit: {added.message}")
    nvda = next(p for p in updated.positions if p.ticker == "NVDA")
    if nvda.blended_cost_basis != 120.0:
        raise AssertionError(f"expected NVDA cost 120, got {nvda.blended_cost_basis}")

    _, bad_cost = add_ticker_to_portfolio(updated, "NVDA", shares=1, cost_basis=0)
    if bad_cost.success:
        raise AssertionError("zero cost basis should fail")

    updated, missing = remove_ticker_from_portfolio(updated, "TSLA")
    if missing.success:
        raise AssertionError("remove missing ticker should fail")

    updated, removed = remove_ticker_from_portfolio(updated, "AAPL")
    if not removed.success or len(updated.positions) != 1:
        raise AssertionError(f"remove failed: {removed}")

    portfolio = Portfolio(
        positions=[
            Position(
                ticker="MSFT",
                lots=[PositionLot(shares=10, cost=400.0, date="unknown")],
            )
        ],
        cash=1000.0,
    )
    with _FX_PATCH:
        updated, sold = sell_ticker_from_portfolio(
            portfolio,
            "MSFT",
            sell_price=420.0,
            shares=4.0,
        )
    if not sold.success or sold.proceeds != 1680.0:
        raise AssertionError(f"partial sell failed: {sold}")
    expected_cash = 1000.0 + 1680.0 * 7.85
    if abs(updated.cash - expected_cash) > 0.01:
        raise AssertionError(f"unexpected cash after partial sell: {updated.cash}")
    msft = next(p for p in updated.positions if p.ticker == "MSFT")
    if msft.shares != 6:
        raise AssertionError(f"expected 6 MSFT shares, got {msft.shares}")

    with _FX_PATCH:
        updated, sold_all = sell_ticker_from_portfolio(updated, "MSFT", sell_price=425.0)
    if not sold_all.success or not sold_all.fully_sold:
        raise AssertionError(f"full sell failed: {sold_all}")
    if updated.positions:
        raise AssertionError("position should be removed after full sell")
    expected_total_cash = expected_cash + 6 * 425.0 * 7.85
    if abs(updated.cash - expected_total_cash) > 0.01:
        raise AssertionError(f"unexpected cash after full sell: {updated.cash}")

    portfolio = Portfolio(positions=[], cash=100.0)
    updated, deposited = deposit_cash_to_portfolio(portfolio, 500.0)
    if not deposited.success or updated.cash != 600.0:
        raise AssertionError(f"HKD deposit failed: {deposited}")
    updated, usd_deposit = deposit_cash_to_portfolio(updated, 200.0, currency="USD")
    if not usd_deposit.success or updated.cash_usd != 200.0:
        raise AssertionError(f"USD deposit failed: {usd_deposit}")
    with patch(
        "analysis.portfolio_valuation.fetch_fx_rates_to_hkd",
        return_value={"JPY": 0.05, "USD": 7.85, "HKD": 1.0},
    ):
        updated, jpy_deposit = deposit_cash_to_portfolio(updated, 10000.0, currency="JPY")
    if not jpy_deposit.success or updated.cash_jpy != 10000.0:
        raise AssertionError(f"JPY deposit failed: {jpy_deposit}")
    expected_cash_hkd = 600.0 + 200.0 * 7.85 + 10000.0 * 0.05
    if abs(jpy_deposit.cash_balance_hkd - expected_cash_hkd) > 0.01:
        raise AssertionError(
            f"JPY deposit HKD total wrong: {jpy_deposit.cash_balance_hkd}"
        )
    _, bad_deposit = deposit_cash_to_portfolio(updated, 0)
    if bad_deposit.success:
        raise AssertionError("zero deposit should fail")

    with _FX_PATCH:
        cash_portfolio = Portfolio(positions=[], cash=50_000.0)
        updated_hk, hk_buy = add_ticker_to_portfolio(
            cash_portfolio,
            "1810.HK",
            shares=100,
            cost_basis=25.0,
        )
    if not hk_buy.success or updated_hk.cash != 50_000.0 - 100 * 25.0:
        raise AssertionError(f"HKD buy should debit cash: {hk_buy}")

    with _FX_PATCH:
        usd_portfolio = Portfolio(positions=[], cash=0.0, cash_usd=100.0)
        _, insufficient = add_ticker_to_portfolio(
            usd_portfolio,
            "MU",
            shares=1,
            cost_basis=943.31,
        )
    if insufficient.success:
        raise AssertionError("buy should fail when cash is insufficient")

    with _FX_PATCH:
        usd_portfolio = Portfolio(positions=[], cash=10_000.0, cash_usd=1_000.0)
        updated_mu, mu_buy = add_ticker_to_portfolio(
            usd_portfolio,
            "MU",
            shares=1,
            cost_basis=943.31,
        )
    if not mu_buy.success or abs(updated_mu.cash_usd - (1_000.0 - 943.31)) > 1e-9:
        raise AssertionError(f"USD buy should debit cash_usd: {mu_buy}")

    temp_dir = Path(tempfile.mkdtemp(prefix="portfolio-edit-test-"))
    try:
        paths = resolve_data_paths(temp_dir)
        repo = DataRepository(paths)
        repo.save_portfolio(
            Portfolio(
                positions=[
                    Position(
                        ticker="MSFT",
                        lots=[PositionLot(shares=2, cost=300.0, date="2026-01-01")],
                    )
                ],
                cash_usd=1_000.0,
            )
        )

        with patch(
            "storage.portfolio_ops.verify_ticker_exists",
            return_value=None,
        ):
            result = repo.add_ticker_to_portfolio("GOOG", shares=3, cost_basis=140.0)
        if not result.success:
            raise AssertionError(f"repository add failed: {result.message}")

        loaded = repo.load_portfolio()
        tickers = {position.ticker for position in loaded.positions}
        if tickers != {"MSFT", "GOOG"}:
            raise AssertionError(f"unexpected tickers after add: {tickers}")

        raw = json.loads(paths.portfolio.read_text(encoding="utf-8"))
        msft_row = raw["positions"][0]
        if "shares" in msft_row or "cost_basis" in msft_row:
            raise AssertionError("persisted portfolio should store lots, not legacy fields")
        if "lots" not in msft_row:
            raise AssertionError("persisted portfolio missing lots")

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
