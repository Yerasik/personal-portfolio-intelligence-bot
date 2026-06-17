"""Deterministic portfolio risk estimate vs client limits (no LLM)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from analysis.portfolio_valuation import build_portfolio_valuation
from analysis.risk_metrics import (
    PortfolioHistoricalMetrics,
    compute_portfolio_historical_metrics,
    herfindahl_index,
)
from analysis.rules import AlertCandidate
from collectors.market_data import portfolio_tickers
from storage.models import AppConfig, BotState, Portfolio, RiskProfile, SignalsFile

RiskLevel = Literal["low", "moderate", "elevated", "high"]


@dataclass(frozen=True)
class PortfolioRiskMetrics:
    """Objective risk measures shown in /analyze."""

    annual_volatility_pct: float | None
    max_drawdown_pct: float | None
    herfindahl_index: float | None
    max_holding_weight_pct: float | None
    observation_days: int


@dataclass(frozen=True)
class PortfolioRiskAssessment:
    """Rule-based portfolio risk snapshot vs configured client limits."""

    level: RiskLevel
    score: float
    factors: tuple[str, ...]
    metrics: PortfolioRiskMetrics
    within_limits: bool
    profile: RiskProfile


def estimate_portfolio_risk(
    portfolio: Portfolio,
    state: BotState,
    signals: SignalsFile,
    alerts: list[AlertCandidate],
    app_config: AppConfig,
    *,
    historical_metrics: PortfolioHistoricalMetrics | None = None,
) -> PortfolioRiskAssessment:
    """Estimate portfolio risk from historical metrics, limits, sentiment, and alerts."""
    profile = app_config.risk_profile

    if not portfolio.positions:
        return PortfolioRiskAssessment(
            level="low",
            score=0.0,
            factors=("Portfolio is empty.",),
            metrics=_empty_metrics(),
            within_limits=True,
            profile=profile,
        )

    valuation = build_portfolio_valuation(portfolio, state)
    weights_pct = {
        item.ticker: item.weight_pct or 0.0 for item in valuation.positions
    }
    max_weight = max(weights_pct.values()) if weights_pct else None
    hhi = herfindahl_index(list(weights_pct.values()))

    if historical_metrics is None:
        historical_metrics = compute_portfolio_historical_metrics(
            weights_pct,
            lookback_months=profile.volatility_lookback_months,
        )

    metrics = PortfolioRiskMetrics(
        annual_volatility_pct=historical_metrics.annual_volatility_pct,
        max_drawdown_pct=historical_metrics.max_drawdown_pct,
        herfindahl_index=hhi,
        max_holding_weight_pct=max_weight,
        observation_days=historical_metrics.observation_days,
    )

    score = 0.0
    factors: list[str] = []
    breaches = 0

    if metrics.annual_volatility_pct is not None:
        factors.append(
            _format_metric_factor(
                "Annual volatility",
                metrics.annual_volatility_pct,
                profile.max_annual_volatility_pct,
                suffix="%",
            )
        )
        pressure = _limit_pressure(
            metrics.annual_volatility_pct,
            profile.max_annual_volatility_pct,
        )
        score += pressure * 40.0
        if pressure > 0:
            breaches += 1
    else:
        factors.append(
            "Historical volatility unavailable (insufficient price history)."
        )

    if metrics.max_drawdown_pct is not None:
        drawdown_abs = abs(metrics.max_drawdown_pct)
        factors.append(
            _format_metric_factor(
                f"Max drawdown ({profile.volatility_lookback_months}mo)",
                drawdown_abs,
                profile.max_drawdown_pct,
                suffix="%",
            )
        )
        pressure = _limit_pressure(drawdown_abs, profile.max_drawdown_pct)
        score += pressure * 35.0
        if pressure > 0:
            breaches += 1
    else:
        factors.append(
            f"Max drawdown unavailable ({profile.volatility_lookback_months}mo lookback)."
        )

    if max_weight is not None:
        factors.append(
            _format_metric_factor(
                "Largest holding",
                max_weight,
                profile.max_single_holding_pct,
                suffix="%",
            )
        )
        pressure = _limit_pressure(max_weight, profile.max_single_holding_pct)
        score += pressure * 25.0
        if pressure > 0:
            breaches += 1
        if hhi is not None:
            factors.append(f"Concentration index (HHI): {hhi:.2f} (lower is more diversified).")

    score += _supplemental_score(portfolio, state, signals, alerts, app_config, factors)
    score = min(100.0, score)
    within_limits = breaches == 0 and score < 51.0
    level = _level_for_score(score, breaches=breaches, profile=profile, metrics=metrics)

    if breaches == 0 and score < 26 and not any(
        "sentiment" in factor.lower() or "alert" in factor.lower() for factor in factors
    ):
        factors.append("Within configured volatility, drawdown, and concentration limits.")

    return PortfolioRiskAssessment(
        level=level,
        score=score,
        factors=tuple(factors),
        metrics=metrics,
        within_limits=within_limits,
        profile=profile,
    )


def _supplemental_score(
    portfolio: Portfolio,
    state: BotState,
    signals: SignalsFile,
    alerts: list[AlertCandidate],
    app_config: AppConfig,
    factors: list[str],
) -> float:
    """Add smaller adjustments from sentiment, recent moves, and alerts."""
    score = 0.0

    if app_config.risk_profile.include_sentiment_in_score:
        sentiment_scores = [
            record.score
            for symbol in portfolio_tickers(portfolio)
            if (record := signals.sentiment.get(symbol)) is not None
        ]
        if sentiment_scores:
            avg_sentiment = sum(sentiment_scores) / len(sentiment_scores)
            if avg_sentiment <= -0.35:
                score += 8
                factors.append(f"Bearish news sentiment average ({avg_sentiment:+.2f}).")
            elif avg_sentiment <= -0.15:
                score += 4
                factors.append(f"Soft news sentiment average ({avg_sentiment:+.2f}).")

    urgent = sum(1 for alert in alerts if alert.urgency == "urgent")
    warning = sum(1 for alert in alerts if alert.urgency == "warning")
    if urgent:
        score += min(10, urgent * 6)
        factors.append(f"{urgent} urgent rule alert(s) active.")
    if warning:
        score += min(6, warning * 3)
        factors.append(f"{warning} warning rule alert(s) active.")

    return score


def _format_metric_factor(
    label: str,
    actual: float,
    limit: float,
    *,
    suffix: str,
) -> str:
    status = "within limit" if actual <= limit else "above limit"
    return f"{label}: {actual:.1f}{suffix} (limit {limit:.1f}{suffix}, {status})."


def _limit_pressure(actual: float, limit: float) -> float:
    """Return 0–1 pressure where 1 means at or above 2× the configured limit."""
    if limit <= 0:
        return 0.0
    if actual <= limit:
        return actual / limit * 0.5
    overrun = (actual - limit) / limit
    return min(1.0, 0.5 + overrun)


def _level_for_score(
    score: float,
    *,
    breaches: int,
    profile: RiskProfile,
    metrics: PortfolioRiskMetrics,
) -> RiskLevel:
    if profile.risk_metric_primary == "volatility":
        vol = metrics.annual_volatility_pct
        if vol is not None:
            if vol > profile.max_annual_volatility_pct * 1.25:
                return "high"
            if vol > profile.max_annual_volatility_pct:
                return "elevated"
    if breaches >= 2 or score >= 76:
        return "high"
    if breaches >= 1 or score >= 51:
        return "elevated"
    if score >= 26:
        return "moderate"
    return "low"


def _empty_metrics() -> PortfolioRiskMetrics:
    return PortfolioRiskMetrics(
        annual_volatility_pct=None,
        max_drawdown_pct=None,
        herfindahl_index=None,
        max_holding_weight_pct=None,
        observation_days=0,
    )
