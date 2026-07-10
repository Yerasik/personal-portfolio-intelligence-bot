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


def test_us_listed_selloff_hits_usd_holdings() -> None:
    portfolio = Portfolio(
        positions=[
            Position(
                ticker="VRT",
                lots=[PositionLot(shares=2, cost=318.2, date="2026-01-01")],
            ),
            Position(
                ticker="1810.HK",
                lots=[PositionLot(shares=100, cost=25.0, date="2026-01-01")],
            ),
        ],
    )
    state = BotState(
        latest_prices={
            "VRT": _quote("VRT", 320.0, industry="Electrical Equipment & Parts"),
            "1810.HK": _quote("1810.HK", 26.0, industry="Consumer Electronics"),
        }
    )
    scenario = next(
        item for item in DEFAULT_STRESS_SCENARIOS if item.scenario_id == "us_listed_selloff"
    )
    report = run_stress_report(
        portfolio,
        state,
        [scenario],
        ticker_to_industry={
            "VRT": "Electrical Equipment & Parts",
            "1810.HK": "Consumer Electronics",
        },
    )
    if report is None:
        raise AssertionError("expected stress report")
    result = report.scenarios[0]
    if result.delta_hkd >= 0:
        raise AssertionError("US sell-off should reduce portfolio value")
    if result.fx_note:
        raise AssertionError("peg-intact scenario should not show FX note")
    vrt = next(item for item in result.impacts if item.ticker == "VRT")
    hk = next(item for item in result.impacts if item.ticker == "1810.HK")
    if vrt.delta_hkd >= hk.delta_hkd:
        raise AssertionError("VRT should be hit harder than HK listing in US sell-off")


def test_jpy_weaker_reduces_jpy_cash_value() -> None:
    portfolio = Portfolio(
        positions=[
            Position(
                ticker="VRT",
                lots=[PositionLot(shares=1, cost=100.0, date="2026-01-01")],
            ),
        ],
        cash_jpy=100_000.0,
    )
    state = BotState(
        latest_prices={
            "VRT": _quote("VRT", 100.0, industry="Electrical Equipment & Parts"),
        }
    )
    scenario = next(item for item in DEFAULT_STRESS_SCENARIOS if item.scenario_id == "jpy_weaker")
    report = run_stress_report(
        portfolio,
        state,
        [scenario],
        ticker_to_industry={"VRT": "Electrical Equipment & Parts"},
    )
    if report is None:
        raise AssertionError("expected stress report")
    result = report.scenarios[0]
    if result.delta_hkd >= 0:
        raise AssertionError("JPY weakening should reduce HKD portfolio value")
    if "JPY/HKD" not in result.fx_note:
        raise AssertionError(f"missing JPY FX note: {result.fx_note}")


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
        scenario_id="us_listed_selloff",
        title="Custom US sell-off",
        market_return_pct=-6.0,
    )
    merged = effective_stress_scenarios(AppConfig(stress_scenarios=[custom]))
    match = next(item for item in merged if item.scenario_id == "us_listed_selloff")
    if match.title != "Custom US sell-off":
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


def test_portfolio_holdings_get_meaningful_shocks() -> None:
    """Portfolio-like mix: HK tech, datacenter, gold, rare earths."""
    portfolio = Portfolio(
        positions=[
            Position(
                ticker="1810.HK",
                lots=[PositionLot(shares=200, cost=31.81, date="2026-01-01")],
            ),
            Position(
                ticker="VRT",
                lots=[PositionLot(shares=2, cost=318.2, date="2026-01-01")],
            ),
            Position(
                ticker="GLDM",
                lots=[PositionLot(shares=10, cost=86.4, date="2026-01-01")],
            ),
            Position(
                ticker="MP",
                lots=[PositionLot(shares=10, cost=59.38, date="2026-01-01")],
            ),
        ]
    )
    state = BotState(
        latest_prices={
            "1810.HK": _quote("1810.HK", 26.0, industry="Consumer Electronics"),
            "VRT": _quote("VRT", 320.0, industry="Electrical Equipment & Parts"),
            "GLDM": _quote("GLDM", 81.0),
            "MP": _quote("MP", 52.0, industry="Other Industrial Metals & Mining"),
        }
    )
    industries = {
        "1810.HK": "Consumer Electronics",
        "VRT": "Electrical Equipment & Parts",
        "MP": "Other Industrial Metals & Mining",
    }
    china = next(
        item for item in DEFAULT_STRESS_SCENARIOS if item.scenario_id == "china_hk_risk_off"
    )
    report = run_stress_report(portfolio, state, [china], ticker_to_industry=industries)
    if report is None:
        raise AssertionError("expected china HK report")
    result = report.scenarios[0]
    if result.delta_hkd >= 0:
        raise AssertionError("china HK risk-off should hurt this portfolio")
    tickers_hit = {item.ticker for item in result.impacts if item.shock_pct < 0}
    if "1810.HK" not in tickers_hit:
        raise AssertionError(f"1810.HK should be shocked, impacts={result.impacts}")

    rare_earth = next(
        item
        for item in DEFAULT_STRESS_SCENARIOS
        if item.scenario_id == "rare_earth_supply_shock"
    )
    mp_report = run_stress_report(
        portfolio, state, [rare_earth], ticker_to_industry=industries
    )
    if mp_report is None:
        raise AssertionError("expected rare earth report")
    mp_impact = next(
        item for item in mp_report.scenarios[0].impacts if item.ticker == "MP"
    )
    if mp_impact.shock_pct != -17.0:
        raise AssertionError(f"MP shock wrong: {mp_impact.shock_pct}")

    risk_off = next(
        item for item in DEFAULT_STRESS_SCENARIOS if item.scenario_id == "global_risk_off"
    )
    gold_report = run_stress_report(
        portfolio, state, [risk_off], ticker_to_industry=industries
    )
    if gold_report is None:
        raise AssertionError("expected global risk-off report")
    gldm = next(
        item for item in gold_report.scenarios[0].impacts if item.ticker == "GLDM"
    )
    if gldm.delta_hkd <= 0:
        raise AssertionError("GLDM should gain in global risk-off scenario")


def main() -> None:
    test_us_listed_selloff_hits_usd_holdings()
    test_jpy_weaker_reduces_jpy_cash_value()
    test_ai_capex_finds_nvda_as_worst()
    test_resolve_shock_priority_ticker_over_sector()
    test_effective_scenarios_merge_config()
    test_format_stress_report_renders()
    test_portfolio_holdings_get_meaningful_shocks()
    print("test_scenario_stress: OK")


if __name__ == "__main__":
    main()
