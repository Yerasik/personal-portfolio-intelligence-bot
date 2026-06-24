"""Portfolio performance snapshot persistence."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from analysis.portfolio_valuation import build_portfolio_valuation
from storage.models import (
    BotState,
    PerformanceHistory,
    Portfolio,
    PortfolioPerformanceSnapshot,
    PositionPerformancePoint,
)
from storage.repository import DataRepository

logger = logging.getLogger(__name__)

_DAILY_LOOKBACK = timedelta(hours=24)


def build_portfolio_snapshot(
    portfolio: Portfolio,
    state: BotState,
    *,
    history: PerformanceHistory | None = None,
    captured_at: datetime | None = None,
) -> PortfolioPerformanceSnapshot | None:
    """Build a snapshot from the current portfolio and cached quotes."""
    if not portfolio.positions and portfolio.cash <= 0:
        return None

    timestamp = captured_at or datetime.now(tz=UTC)
    valuation = build_portfolio_valuation(portfolio, state)
    total_value = valuation.total_market_value_hkd + portfolio.cash
    total_cost = (
        valuation.total_cost_value_hkd + portfolio.cash
        if valuation.total_cost_value_hkd is not None
        else portfolio.cash
    )

    positions: dict[str, PositionPerformancePoint] = {}
    for item in valuation.positions:
        if item.price is None or item.market_value_hkd is None:
            continue
        positions[item.ticker] = PositionPerformancePoint(
            price=item.price,
            value=item.market_value_hkd,
        )

    daily_pnl_pct = _daily_pnl_pct(
        total_value,
        timestamp=timestamp,
        history=history,
    )

    return PortfolioPerformanceSnapshot(
        timestamp=timestamp,
        total_value=total_value,
        total_cost=total_cost,
        daily_pnl_pct=daily_pnl_pct,
        positions=positions,
    )


def save_portfolio_snapshot(repository: DataRepository) -> PortfolioPerformanceSnapshot | None:
    """Append a timestamped valuation record to performance_history.json."""
    portfolio = repository.load_portfolio()
    state = repository.load_state()
    history = repository.load_performance_history()
    snapshot = build_portfolio_snapshot(
        portfolio,
        state,
        history=history,
        captured_at=state.last_market_fetch_at or datetime.now(tz=UTC),
    )
    if snapshot is None:
        logger.info("Skipping performance snapshot: empty portfolio")
        return None

    repository.append_performance_snapshot(snapshot)
    logger.info(
        "Appended performance snapshot: value=%.2f cost=%.2f daily_pnl=%.2f%%",
        snapshot.total_value,
        snapshot.total_cost,
        snapshot.daily_pnl_pct,
    )
    return snapshot


def _daily_pnl_pct(
    total_value: float,
    *,
    timestamp: datetime,
    history: PerformanceHistory | None,
) -> float:
    """Return day-over-day portfolio change vs the nearest prior snapshot."""
    if history is None or not history.snapshots:
        return 0.0

    prior_value = _value_at_or_before(
        history.snapshots,
        timestamp - _DAILY_LOOKBACK,
    )
    if prior_value is None or prior_value <= 0:
        return 0.0
    return ((total_value - prior_value) / prior_value) * 100.0


def _value_at_or_before(
    snapshots: list[PortfolioPerformanceSnapshot],
    target: datetime,
) -> float | None:
    """Return total_value from the latest snapshot at or before target."""
    if target.tzinfo is None:
        target = target.replace(tzinfo=UTC)

    prior: PortfolioPerformanceSnapshot | None = None
    for item in sorted(snapshots, key=lambda row: row.timestamp):
        ts = item.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        if ts <= target:
            prior = item
        else:
            break
    return prior.total_value if prior is not None else None
