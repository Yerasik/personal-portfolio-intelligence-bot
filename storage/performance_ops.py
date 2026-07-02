"""Portfolio performance snapshot persistence."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from analysis.portfolio_valuation import (
    build_portfolio_valuation,
    portfolio_cash_hkd,
    portfolio_total_value_hkd,
)
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


def holdings_value_hkd(snapshot: PortfolioPerformanceSnapshot) -> float:
    """Sum position market values in HKD for one snapshot."""
    return sum(point.value for point in snapshot.positions.values())


def repair_performance_history(
    history: PerformanceHistory,
    *,
    latest_cash_hkd: float | None = None,
) -> PerformanceHistory:
    """Rebuild snapshot totals from position values and optional cash."""
    if not history.snapshots:
        return history

    snapshots = sorted(history.snapshots, key=lambda row: row.timestamp)
    repaired: list[PortfolioPerformanceSnapshot] = []
    changed = False
    for index, snapshot in enumerate(snapshots):
        holdings = holdings_value_hkd(snapshot)
        is_latest = index == len(snapshots) - 1
        if snapshot.cash_hkd is not None:
            cash_hkd = snapshot.cash_hkd
        elif is_latest and latest_cash_hkd is not None:
            cash_hkd = latest_cash_hkd
        else:
            cash_hkd = 0.0

        total_value = holdings + cash_hkd
        new_cash_field = cash_hkd if snapshot.cash_hkd is not None or is_latest else None
        if (
            abs(total_value - snapshot.total_value) > 0.01
            or new_cash_field != snapshot.cash_hkd
        ):
            changed = True
        repaired.append(
            snapshot.model_copy(
                update={
                    "total_value": total_value,
                    "cash_hkd": new_cash_field,
                }
            )
        )

    if not changed:
        return history
    return history.model_copy(update={"snapshots": repaired})


def prune_performance_history(
    history: PerformanceHistory,
    *,
    retention_days: int,
    now: datetime | None = None,
) -> PerformanceHistory:
    """Drop raw snapshots older than retention_days; always keep the latest."""
    if not history.snapshots or retention_days <= 0:
        return history

    evaluated_at = now or datetime.now(tz=UTC)
    if evaluated_at.tzinfo is None:
        evaluated_at = evaluated_at.replace(tzinfo=UTC)
    cutoff = evaluated_at - timedelta(days=retention_days)

    ordered = sorted(history.snapshots, key=lambda row: row.timestamp)
    kept = [
        row
        for row in ordered
        if _snapshot_ts(row) >= cutoff
    ]
    if len(kept) == len(ordered):
        return history
    if not kept:
        kept = [ordered[-1]]

    return history.model_copy(update={"snapshots": kept})


def _snapshot_ts(snapshot: PortfolioPerformanceSnapshot) -> datetime:
    ts = snapshot.timestamp
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


def build_portfolio_snapshot(
    portfolio: Portfolio,
    state: BotState,
    *,
    history: PerformanceHistory | None = None,
    captured_at: datetime | None = None,
) -> PortfolioPerformanceSnapshot | None:
    """Build a snapshot from the current portfolio and cached quotes."""
    valuation = build_portfolio_valuation(portfolio, state)
    cash_hkd = portfolio_cash_hkd(portfolio, usd_to_hkd=valuation.usd_to_hkd)
    if not portfolio.positions and cash_hkd <= 0:
        return None

    timestamp = captured_at or datetime.now(tz=UTC)
    total_value = portfolio_total_value_hkd(portfolio, valuation)
    total_cost = (
        valuation.total_cost_value_hkd + cash_hkd
        if valuation.total_cost_value_hkd is not None
        else cash_hkd
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
        cash_hkd=cash_hkd,
        positions=positions,
    )


def save_portfolio_snapshot(repository: DataRepository) -> PortfolioPerformanceSnapshot | None:
    """Append a timestamped valuation record to performance_history.json."""
    portfolio = repository.load_portfolio()
    state = repository.load_state()
    app_config = repository.load_config()
    history = repository.load_performance_history()
    valuation = build_portfolio_valuation(portfolio, state)
    cash_hkd = portfolio_cash_hkd(portfolio, usd_to_hkd=valuation.usd_to_hkd)

    pruned_history = prune_performance_history(
        history,
        retention_days=app_config.performance_history_retention_days,
    )
    if pruned_history is not history:
        repository.save_performance_history(pruned_history)
        history = pruned_history

    repaired_history = repair_performance_history(
        history,
        latest_cash_hkd=cash_hkd,
    )
    if repaired_history is not history:
        repository.save_performance_history(repaired_history)
        history = repaired_history

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
