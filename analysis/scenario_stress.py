"""Scenario stress testing: simulate portfolio impact under macro/sector shocks."""

from __future__ import annotations

from dataclasses import dataclass

from analysis.portfolio_valuation import (
    HKD,
    _DEFAULT_JPY_TO_HKD,
    build_portfolio_valuation,
    portfolio_total_value_hkd,
)
from storage.models import AppConfig, BotState, Portfolio, StressScenario

DEFAULT_STRESS_SCENARIOS: tuple[StressScenario, ...] = (
    StressScenario(
        scenario_id="us_listed_selloff",
        title="US equities sell-off (HKD peg intact)",
        description=(
            "US earnings miss, guidance cut, or rates scare hits NYSE/Nasdaq names. "
            "HKD–USD peg assumed unchanged — impact is from USD share prices, not FX."
        ),
        market_return_pct=-3.0,
        sector_return_pct={
            "electrical equipment": -9.0,
            "hong kong equities": -4.0,
            "other industrial metals & mining": -7.0,
        },
        ticker_return_pct={
            "VRT": -9.0,
            "GLDM": 2.5,
            "XYL": -5.5,
            "MP": -8.0,
            "1810.HK": -4.0,
            "0100.HK": -5.0,
        },
    ),
    StressScenario(
        scenario_id="fed_higher_for_longer",
        title="Fed higher-for-longer (yields spike)",
        description=(
            "CPI surprises to the upside; markets price fewer cuts and higher terminal "
            "rates. Growth/long-duration assets sell off; gold gets modest haven bid."
        ),
        market_return_pct=-3.5,
        sector_return_pct={
            "consumer electronics": -7.0,
            "software": -6.0,
            "us semiconductors": -9.0,
            "semiconductors": -8.0,
            "electrical equipment": -11.0,
            "hong kong equities": -5.0,
        },
        ticker_return_pct={
            "VRT": -12.0,
            "GLDM": 4.5,
            "1810.HK": -6.0,
            "0100.HK": -7.0,
            "XYL": -3.5,
        },
    ),
    StressScenario(
        scenario_id="china_hk_risk_off",
        title="China / HK risk-off",
        description=(
            "Geopolitical or regulatory headline shock — tariffs, export controls, weak "
            "China data, or HK liquidity concerns. HK tech and China-linked names reprice."
        ),
        sector_return_pct={
            "china-us relations": -12.0,
            "consumer electronics": -11.0,
            "hong kong equities": -9.0,
            "internet content": -14.0,
            "software": -8.0,
        },
        ticker_return_pct={
            "1810.HK": -13.0,
            "0100.HK": -15.0,
            "0700.HK": -12.0,
            "9988.HK": -14.0,
            "BABA": -13.0,
            "3690.HK": -14.0,
        },
    ),
    StressScenario(
        scenario_id="ai_capex_slowdown",
        title="AI / datacenter capex scare",
        description=(
            "Hyperscaler capex guidance disappoints or GPU lead times shorten. "
            "Semis and datacenter power/cooling vendors hit hardest; broad tech softer."
        ),
        market_return_pct=-2.5,
        sector_return_pct={
            "ai": -14.0,
            "us semiconductors": -12.0,
            "semiconductors": -10.0,
            "electrical equipment": -15.0,
        },
        ticker_return_pct={
            "NVDA": -16.0,
            "AMD": -14.0,
            "MU": -13.0,
            "AVGO": -11.0,
            "TSM": -10.0,
            "VRT": -18.0,
        },
    ),
    StressScenario(
        scenario_id="rare_earth_supply_shock",
        title="Rare-earth / magnet supply shock",
        description=(
            "China tightens rare-earth or magnet exports; EV/defence supply-chain fears "
            "flare. Critical-mineral miners volatile; downstream users reprice demand risk."
        ),
        ticker_return_pct={
            "MP": -17.0,
        },
        sector_return_pct={
            "other industrial metals & mining": -12.0,
            "basic materials": -6.0,
            "china-us relations": -8.0,
        },
    ),
    StressScenario(
        scenario_id="global_risk_off",
        title="Global risk-off week",
        description=(
            "Sudden macro shock — bank stress, recession scare, or geopolitical "
            "escalation. Broad equity drawdown; gold ETF tends to outperform as ballast."
        ),
        market_return_pct=-6.5,
        sector_return_pct={
            "hong kong equities": -8.0,
            "consumer electronics": -7.0,
        },
        ticker_return_pct={
            "GLDM": 7.0,
            "XYL": -4.0,
            "1810.HK": -9.0,
            "VRT": -10.0,
            "MP": -11.0,
        },
    ),
    StressScenario(
        scenario_id="jpy_weaker",
        title="JPY weakens vs HKD (−10%)",
        description=(
            "BoJ stays dovish, carry-trade unwind, or Japan fiscal concerns — yen falls "
            "vs HKD. JPY cash loses HKD value; USD/HKD peg unchanged."
        ),
        jpy_to_hkd_change_pct=-10.0,
    ),
)


@dataclass(frozen=True)
class StressPositionImpact:
    """Per-holding impact under one stress scenario."""

    ticker: str
    industry: str
    shock_pct: float
    baseline_value_hkd: float
    stressed_value_hkd: float
    delta_hkd: float
    delta_pct: float


@dataclass(frozen=True)
class StressScenarioResult:
    """Portfolio impact for one stress scenario."""

    scenario_id: str
    title: str
    description: str
    baseline_total_hkd: float
    stressed_total_hkd: float
    delta_hkd: float
    delta_pct: float
    fx_note: str
    impacts: tuple[StressPositionImpact, ...]


@dataclass(frozen=True)
class StressReport:
    """Full stress test output."""

    baseline_total_hkd: float
    scenarios: tuple[StressScenarioResult, ...]


def effective_stress_scenarios(app_config: AppConfig) -> list[StressScenario]:
    """Return built-in scenarios merged with config overrides by scenario_id."""
    by_id = {item.scenario_id: item for item in DEFAULT_STRESS_SCENARIOS}
    for item in app_config.stress_scenarios:
        by_id[item.scenario_id] = item
    return list(by_id.values())


def resolve_ticker_industry(
    ticker: str,
    *,
    ticker_to_industry: dict[str, str],
    state: BotState,
) -> str:
    """Resolve an industry label for sector shock matching."""
    symbol = ticker.strip().upper()
    mapped = ticker_to_industry.get(symbol, "").strip()
    if mapped:
        return mapped

    quote = state.latest_prices.get(symbol)
    if quote is not None:
        if quote.industry.strip():
            return quote.industry.strip()
        if quote.sector.strip():
            return quote.sector.strip()

    if symbol.endswith(".HK"):
        return "Hong Kong equities"
    return "Unclassified"


def _normalize_shock_map(values: dict[str, float]) -> dict[str, float]:
    return {key.strip().upper(): value for key, value in values.items()}


def _normalize_sector_map(values: dict[str, float]) -> dict[str, float]:
    return {key.strip().lower(): value for key, value in values.items()}


def resolve_position_shock_pct(
    ticker: str,
    industry: str,
    scenario: StressScenario,
) -> float:
    """Return the price shock (%) applied to one holding."""
    ticker_shocks = _normalize_shock_map(scenario.ticker_return_pct)
    symbol = ticker.strip().upper()
    if symbol in ticker_shocks:
        return ticker_shocks[symbol]

    industry_key = industry.strip().lower()
    sector_shocks = _normalize_sector_map(scenario.sector_return_pct)
    if industry_key in sector_shocks:
        return sector_shocks[industry_key]

    for sector, shock in sector_shocks.items():
        if sector in industry_key or industry_key in sector:
            return shock

    if scenario.market_return_pct is not None:
        return scenario.market_return_pct
    return 0.0


def _portfolio_total_hkd(
    portfolio: Portfolio,
    valuation,
    *,
    fx_rates: dict[str, float] | None = None,
) -> float:
    """Total portfolio value in HKD including multi-currency cash at given FX rates."""
    from analysis.cash_balances import portfolio_cash_total_hkd

    rates = dict(fx_rates or {})
    if "USD" not in rates:
        rates["USD"] = valuation.usd_to_hkd
    cash_hkd = portfolio_cash_total_hkd(
        portfolio,
        usd_to_hkd=rates.get("USD"),
        jpy_to_hkd=rates.get("JPY"),
    )
    return valuation.total_market_value_hkd + cash_hkd


def _resolve_fx_rates(
    baseline_usd_to_hkd: float,
    scenario: StressScenario,
    *,
    baseline_jpy_to_hkd: float | None = None,
) -> tuple[dict[str, float], str]:
    """Build shocked FX map and a human-readable FX note."""
    fx_rates = {HKD: 1.0, "USD": baseline_usd_to_hkd}
    fx_parts: list[str] = []

    if scenario.usd_to_hkd is not None:
        shocked = scenario.usd_to_hkd
        fx_rates["USD"] = shocked
        fx_parts.append(f"USD/HKD {baseline_usd_to_hkd:.4f} → {shocked:.4f}")
    elif scenario.usd_to_hkd_change_pct is not None:
        shocked = baseline_usd_to_hkd * (1.0 + scenario.usd_to_hkd_change_pct / 100.0)
        fx_rates["USD"] = shocked
        fx_parts.append(
            f"USD/HKD {baseline_usd_to_hkd:.4f} → {shocked:.4f} "
            f"({scenario.usd_to_hkd_change_pct:+.1f}%)"
        )

    base_jpy = baseline_jpy_to_hkd if baseline_jpy_to_hkd is not None else _DEFAULT_JPY_TO_HKD
    fx_rates["JPY"] = base_jpy
    if scenario.jpy_to_hkd is not None:
        shocked_jpy = scenario.jpy_to_hkd
        fx_rates["JPY"] = shocked_jpy
        fx_parts.append(f"JPY/HKD {base_jpy:.6f} → {shocked_jpy:.6f}")
    elif scenario.jpy_to_hkd_change_pct is not None:
        shocked_jpy = base_jpy * (1.0 + scenario.jpy_to_hkd_change_pct / 100.0)
        fx_rates["JPY"] = shocked_jpy
        fx_parts.append(
            f"JPY/HKD {base_jpy:.6f} → {shocked_jpy:.6f} "
            f"({scenario.jpy_to_hkd_change_pct:+.1f}%)"
        )

    fx_note = " · ".join(fx_parts)
    return fx_rates, fx_note


def _build_shocked_state(
    state: BotState,
    portfolio: Portfolio,
    scenario: StressScenario,
    *,
    ticker_to_industry: dict[str, str],
) -> BotState:
    """Clone bot state with shocked prices for each holding."""
    shocked_quotes = dict(state.latest_prices)
    for position in portfolio.positions:
        symbol = position.ticker.strip().upper()
        industry = resolve_ticker_industry(
            symbol,
            ticker_to_industry=ticker_to_industry,
            state=state,
        )
        shock_pct = resolve_position_shock_pct(symbol, industry, scenario)
        if shock_pct == 0.0:
            continue
        quote = shocked_quotes.get(symbol)
        if quote is None or quote.price is None:
            continue
        shocked_quotes[symbol] = quote.model_copy(
            update={"price": quote.price * (1.0 + shock_pct / 100.0)}
        )
    return state.model_copy(update={"latest_prices": shocked_quotes})


def _position_impacts(
    portfolio: Portfolio,
    baseline_valuation,
    stressed_valuation,
    scenario: StressScenario,
    *,
    ticker_to_industry: dict[str, str],
    state: BotState,
) -> tuple[StressPositionImpact, ...]:
    baseline_by_ticker = {item.ticker: item for item in baseline_valuation.positions}
    stressed_by_ticker = {item.ticker: item for item in stressed_valuation.positions}
    impacts: list[StressPositionImpact] = []

    for position in portfolio.positions:
        symbol = position.ticker.strip().upper()
        baseline_item = baseline_by_ticker.get(symbol)
        stressed_item = stressed_by_ticker.get(symbol)
        baseline_value = (
            baseline_item.market_value_hkd if baseline_item is not None else None
        )
        stressed_value = (
            stressed_item.market_value_hkd if stressed_item is not None else None
        )
        if baseline_value is None or stressed_value is None:
            continue

        industry = resolve_ticker_industry(
            symbol,
            ticker_to_industry=ticker_to_industry,
            state=state,
        )
        shock_pct = resolve_position_shock_pct(symbol, industry, scenario)
        delta_hkd = stressed_value - baseline_value
        delta_pct = (delta_hkd / baseline_value * 100.0) if baseline_value > 0 else 0.0
        impacts.append(
            StressPositionImpact(
                ticker=symbol,
                industry=industry,
                shock_pct=shock_pct,
                baseline_value_hkd=baseline_value,
                stressed_value_hkd=stressed_value,
                delta_hkd=delta_hkd,
                delta_pct=delta_pct,
            )
        )

    impacts.sort(key=lambda item: item.delta_hkd)
    return tuple(impacts)


def run_stress_scenario(
    portfolio: Portfolio,
    state: BotState,
    scenario: StressScenario,
    *,
    ticker_to_industry: dict[str, str],
    baseline_valuation=None,
) -> StressScenarioResult | None:
    """Simulate one scenario and return portfolio + per-holding impact."""
    if baseline_valuation is None:
        baseline_valuation = build_portfolio_valuation(portfolio, state)

    if (
        not portfolio.positions
        and portfolio.cash <= 0
        and portfolio.cash_usd <= 0
        and portfolio.cash_jpy <= 0
    ):
        return None

    from analysis.cash_balances import build_portfolio_cash_balances

    cash_balances = build_portfolio_cash_balances(
        portfolio,
        fx_rates={"USD": baseline_valuation.usd_to_hkd},
    )
    baseline_total = _portfolio_total_hkd(
        portfolio,
        baseline_valuation,
        fx_rates={"USD": baseline_valuation.usd_to_hkd, "JPY": cash_balances.jpy_to_hkd},
    )
    fx_rates, fx_note = _resolve_fx_rates(
        baseline_valuation.usd_to_hkd,
        scenario,
        baseline_jpy_to_hkd=cash_balances.jpy_to_hkd,
    )
    shocked_state = _build_shocked_state(
        state,
        portfolio,
        scenario,
        ticker_to_industry=ticker_to_industry,
    )
    stressed_valuation = build_portfolio_valuation(
        portfolio,
        shocked_state,
        fx_rates=fx_rates,
    )
    stressed_total = _portfolio_total_hkd(
        portfolio,
        stressed_valuation,
        fx_rates=fx_rates,
    )
    delta_hkd = stressed_total - baseline_total
    delta_pct = (delta_hkd / baseline_total * 100.0) if baseline_total > 0 else 0.0
    impacts = _position_impacts(
        portfolio,
        baseline_valuation,
        stressed_valuation,
        scenario,
        ticker_to_industry=ticker_to_industry,
        state=state,
    )

    return StressScenarioResult(
        scenario_id=scenario.scenario_id,
        title=scenario.title,
        description=scenario.description,
        baseline_total_hkd=baseline_total,
        stressed_total_hkd=stressed_total,
        delta_hkd=delta_hkd,
        delta_pct=delta_pct,
        fx_note=fx_note,
        impacts=impacts,
    )


def run_stress_report(
    portfolio: Portfolio,
    state: BotState,
    scenarios: list[StressScenario],
    *,
    ticker_to_industry: dict[str, str],
) -> StressReport | None:
    """Run all requested scenarios against the current portfolio."""
    if not portfolio.positions:
        return None

    baseline_valuation = build_portfolio_valuation(portfolio, state)
    baseline_total = portfolio_total_value_hkd(portfolio, baseline_valuation)
    results: list[StressScenarioResult] = []

    for scenario in scenarios:
        result = run_stress_scenario(
            portfolio,
            state,
            scenario,
            ticker_to_industry=ticker_to_industry,
            baseline_valuation=baseline_valuation,
        )
        if result is not None:
            results.append(result)

    if not results:
        return None

    return StressReport(
        baseline_total_hkd=baseline_total,
        scenarios=tuple(results),
    )
