"""Smoke tests for scenario stress testing."""

from __future__ import annotations

from datetime import datetime, timezone

from analysis.scenario_stress import (
    DEFAULT_STRESS_SCENARIOS,
    effective_stress_scenarios,
    resolve_position_shock_pct,
    run_stress_report,
)
from bot.formatter import format_stress_report
from storage.models import (
    AppConfig,
    BotState,
    MarketQuote,
    Portfolio,
    Position,
    PositionLot,
    StressScenario,
)


def _quote(ticker: str, price: float, *, industry: str = "") -> MarketQuote:
    return MarketQuote(
        ticker=ticker,
        price=price,
        industry=industry,
        currency="USD" if not ticker.endswith(".HK") else "HKD",
        fetched_at=datetime.now(timezone.utc),
    )


def test_usdhkd_scenario_revalues_usd_holdings() -> None:
    portfolio = Portfolio(
        positions=[
            Position(
                ticker="NVDA",
                lots=[PositionLot(shares=10, cost=100.0, date="2026-01-01")],
            )
        ],
        cash_usd=1000.0,
    )
    state = BotState(
        latest_prices={
            "NVDA": _quote("NVDA", 100.0, industry="US Semiconductors"),
        }
    )
    scenario = next(item for item in DEFAULT_STRESS_SCENARIOS if item.scenario_id == "usdhkd_up")
    report = run_stress_report(
        portfolio,
        state,
        [scenario],
        ticker_to_industry={"NVDA": "US Semiconductors"},
    )
    if report is None:
        raise AssertionError("expected stress report")
    result = report.scenarios[0]
    if result.delta_hkd <= 0:
        raise AssertionError(f"USD/HKD up should increase HKD value, got {result.delta_hkd}")
    if "USD/HKD" not in result.fx_note:
        raise AssertionError(f"missing FX note: {result.fx_note}")


def test_ai_capex_finds_nvda_as_worst() -> None:
    portfolio = Portfolio(
        positions=[
            Position(
                ticker="NVDA",
                lots=[PositionLot(shares=5, cost=120.0, date="2026-01-01")],
            ),
            Position(
                ticker="AAPL",
                lots=[PositionLot(shares=10, cost=150.0, date="2026-01-01")],
            ),
        ]
    )
    state = BotState(
        latest_prices={
            "NVDA": _quote("NVDA", 130.0, industry="US Semiconductors"),
            "AAPL": _quote("AAPL", 180.0, industry="Consumer Electronics"),
        }
    )
    scenario = next(
        item for item in DEFAULT_STRESS_SCENARIOS if item.scenario_id == "ai_capex_slowdown"
    )
    report = run_stress_report(
        portfolio,
        state,
        [scenario],
        ticker_to_industry={
            "NVDA": "US Semiconductors",
            "AAPL": "Consumer Electronics",
        },
    )
    if report is None:
        raise AssertionError("expected stress report")
    result = report.scenarios[0]
    if result.delta_hkd >= 0:
        raise AssertionError("AI capex slowdown should reduce portfolio value")
    worst = result.impacts[0]
    if worst.ticker != "NVDA":
        raise AssertionError(f"expected NVDA as worst contributor, got {worst.ticker}")


def test_resolve_shock_priority_ticker_over_sector() -> None:
    scenario = StressScenario(
        scenario_id="test",
        title="Test",
        sector_return_pct={"US Semiconductors": -10.0},
        ticker_return_pct={"NVDA": -30.0},
        market_return_pct=-5.0,
    )
    shock = resolve_position_shock_pct("NVDA", "US Semiconductors", scenario)
    if shock != -30.0:
        raise AssertionError(f"ticker shock should win, got {shock}")


def test_effective_scenarios_merge_config() -> None:
    custom = StressScenario(
        scenario_id="usdhkd_up",
        title="Custom USD move",
        usd_to_hkd_change_pct=5.0,
    )
    merged = effective_stress_scenarios(AppConfig(stress_scenarios=[custom]))
    match = next(item for item in merged if item.scenario_id == "usdhkd_up")
    if match.title != "Custom USD move":
        raise AssertionError("config scenario should override built-in default")


def test_format_stress_report_renders() -> None:
    portfolio = Portfolio(
        positions=[
            Position(
                ticker="NVDA",
                lots=[PositionLot(shares=1, cost=100.0, date="2026-01-01")],
            )
        ]
    )
    state = BotState(latest_prices={"NVDA": _quote("NVDA", 100.0)})
    report = run_stress_report(
        portfolio,
        state,
        [next(item for item in DEFAULT_STRESS_SCENARIOS if item.scenario_id == "ai_capex_slowdown")],
        ticker_to_industry={"NVDA": "US Semiconductors"},
    )
    if report is None:
        raise AssertionError("expected report")
    text = format_stress_report(report)
    if "NVDA" not in text or "Scenario" not in text:
        raise AssertionError(f"unexpected formatted output:\n{text}")


def main() -> None:
    test_usdhkd_scenario_revalues_usd_holdings()
    test_ai_capex_finds_nvda_as_worst()
    test_resolve_shock_priority_ticker_over_sector()
    test_effective_scenarios_merge_config()
    test_format_stress_report_renders()
    print("test_scenario_stress: OK")


if __name__ == "__main__":
    main()
