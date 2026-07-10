"""Smoke tests for canonical cash balance model and formatting."""

from __future__ import annotations

from analysis.cash_balances import (
    build_portfolio_cash_balances,
    format_cash_balance_text,
    portfolio_cash_total_hkd,
)
from analysis.portfolio_valuation import portfolio_cash_hkd
from bot.formatter import format_portfolio
from storage.models import BotState, Portfolio


def test_multi_currency_totals() -> None:
    portfolio = Portfolio(cash=1000.0, cash_usd=63.0, cash_jpy=50_000.0)
    fx_rates = {"USD": 7.85, "JPY": 0.052}
    balances = build_portfolio_cash_balances(portfolio, fx_rates=fx_rates)
    expected = 1000.0 + 63.0 * 7.85 + 50_000.0 * 0.052
    if abs(balances.total_hkd - expected) > 0.01:
        raise AssertionError(f"total_hkd {balances.total_hkd} != {expected}")
    if len(balances.buckets) != 3:
        raise AssertionError(f"expected 3 buckets, got {len(balances.buckets)}")


def test_portfolio_cash_hkd_wrapper() -> None:
    portfolio = Portfolio(cash=500.0, cash_usd=100.0)
    fx_rates = {"USD": 7.8}
    direct = portfolio_cash_total_hkd(portfolio, usd_to_hkd=7.8)
    wrapped = portfolio_cash_hkd(portfolio, usd_to_hkd=7.8)
    if abs(direct - wrapped) > 0.001:
        raise AssertionError("portfolio_cash_hkd wrapper mismatch")
    if abs(direct - (500.0 + 100.0 * 7.8)) > 0.001:
        raise AssertionError(f"unexpected total {direct}")


def test_format_shows_native_and_hkd() -> None:
    portfolio = Portfolio(cash=1000.0, cash_usd=63.0)
    text = format_cash_balance_text(
        portfolio,
        fx_rates={"USD": 7.85},
        include_fx_note=True,
        detailed=True,
    )
    for token in ("HKD", "USD", "7.85", "494"):
        if token not in text:
            raise AssertionError(f"missing {token!r} in:\n{text}")


def test_format_simple_total_only() -> None:
    portfolio = Portfolio(cash=1000.0, cash_usd=63.0)
    text = format_cash_balance_text(
        portfolio,
        fx_rates={"USD": 7.85},
        detailed=False,
    )
    if "@" in text or "FX rates" in text:
        raise AssertionError(f"simple format should not include FX detail:\n{text}")
    if "1,494" not in text and "1494" not in text.replace(",", ""):
        raise AssertionError(f"expected HKD total in:\n{text}")


def test_cash_only_portfolio_view() -> None:
    portfolio = Portfolio(cash_usd=200.0)
    text = format_portfolio(
        portfolio,
        BotState(),
        is_developer=True,
        detailed_cash_display=True,
    )
    if "cash only" not in text.lower() and "nur cash" not in text.lower():
        if "no positions" not in text.lower():
            raise AssertionError(f"expected cash-only header in:\n{text}")
    if "USD" not in text:
        raise AssertionError(f"expected USD bucket in:\n{text}")


def test_cash_only_legacy_shows_empty() -> None:
    portfolio = Portfolio(cash_usd=200.0)
    text = format_portfolio(
        portfolio,
        BotState(),
        is_developer=True,
        detailed_cash_display=False,
    )
    if "empty" not in text.lower() and "leer" not in text.lower():
        raise AssertionError(f"legacy mode should show empty portfolio:\n{text}")


def main() -> None:
    test_multi_currency_totals()
    test_portfolio_cash_hkd_wrapper()
    test_format_shows_native_and_hkd()
    test_format_simple_total_only()
    test_cash_only_portfolio_view()
    test_cash_only_legacy_shows_empty()
    print("test_cash_balances: OK")


if __name__ == "__main__":
    main()
