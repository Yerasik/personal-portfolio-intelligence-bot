"""Deterministic portfolio risk estimate (no LLM)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from analysis.portfolio_valuation import build_portfolio_valuation
from analysis.rules import AlertCandidate
from collectors.market_data import portfolio_tickers
from storage.models import AppConfig, BotState, Portfolio, SignalsFile

RiskLevel = Literal["low", "moderate", "elevated", "high"]


@dataclass(frozen=True)
class PortfolioRiskAssessment:
    """Rule-based portfolio risk snapshot."""

    level: RiskLevel
    score: float
    factors: tuple[str, ...]


def estimate_portfolio_risk(
    portfolio: Portfolio,
    state: BotState,
    signals: SignalsFile,
    alerts: list[AlertCandidate],
    app_config: AppConfig,
) -> PortfolioRiskAssessment:
    """Estimate overall portfolio risk from concentration, P/L, volatility, sentiment, alerts."""
    if not portfolio.positions:
        return PortfolioRiskAssessment(
            level="low",
            score=0.0,
            factors=("Portfolio is empty.",),
        )

    score = 0.0
    factors: list[str] = []

    valuation = build_portfolio_valuation(portfolio, state)
    weights = [
        item.weight_pct
        for item in valuation.positions
        if item.weight_pct is not None
    ]
    if weights:
        max_weight = max(weights)
        if max_weight >= 60:
            score += 28
            factors.append(f"High concentration: largest holding is {max_weight:.0f}% of portfolio.")
        elif max_weight >= 40:
            score += 16
            factors.append(f"Moderate concentration: largest holding is {max_weight:.0f}% of portfolio.")
        elif max_weight >= 30:
            score += 8
            factors.append(f"Largest holding weight is {max_weight:.0f}%.")

    if valuation.total_pl_pct is not None:
        if valuation.total_pl_pct <= -15:
            score += 25
            factors.append(
                f"Large unrealized drawdown: {valuation.total_pl_pct:+.1f}% vs cost basis."
            )
        elif valuation.total_pl_pct <= -5:
            score += 12
            factors.append(
                f"Unrealized loss: {valuation.total_pl_pct:+.1f}% vs cost basis."
            )
        elif valuation.total_pl_pct >= 25:
            score += 6
            factors.append(
                f"Large unrealized gain ({valuation.total_pl_pct:+.1f}%): profit-taking risk."
            )

    moves: list[float] = []
    for symbol in portfolio_tickers(portfolio):
        quote = state.latest_prices.get(symbol)
        if quote is not None and quote.change_pct is not None:
            moves.append(abs(quote.change_pct))
    if moves:
        avg_move = sum(moves) / len(moves)
        if avg_move >= app_config.alert_price_change_pct * 2:
            score += 18
            factors.append(f"High recent volatility: avg |24h move| {avg_move:.1f}%.")
        elif avg_move >= app_config.alert_price_change_pct:
            score += 10
            factors.append(f"Elevated recent volatility: avg |24h move| {avg_move:.1f}%.")

    sentiment_scores = [
        record.score
        for symbol in portfolio_tickers(portfolio)
        if (record := signals.sentiment.get(symbol)) is not None
    ]
    if sentiment_scores:
        avg_sentiment = sum(sentiment_scores) / len(sentiment_scores)
        if avg_sentiment <= -0.35:
            score += 18
            factors.append(f"Bearish news sentiment average ({avg_sentiment:+.2f}).")
        elif avg_sentiment <= -0.15:
            score += 10
            factors.append(f"Soft news sentiment average ({avg_sentiment:+.2f}).")
        elif avg_sentiment >= 0.35:
            score += 4
            factors.append(f"Bullish news sentiment ({avg_sentiment:+.2f}) — watch for hype risk.")

    urgent = sum(1 for alert in alerts if alert.urgency == "urgent")
    warning = sum(1 for alert in alerts if alert.urgency == "warning")
    if urgent:
        score += min(20, urgent * 12)
        factors.append(f"{urgent} urgent rule alert(s) active.")
    if warning:
        score += min(12, warning * 6)
        factors.append(f"{warning} warning rule alert(s) active.")

    score = min(100.0, score)
    level = _level_for_score(score)
    if not factors:
        factors.append("No major risk flags from current rules and market data.")

    return PortfolioRiskAssessment(level=level, score=score, factors=tuple(factors))


def _level_for_score(score: float) -> RiskLevel:
    if score >= 76:
        return "high"
    if score >= 51:
        return "elevated"
    if score >= 26:
        return "moderate"
    return "low"
