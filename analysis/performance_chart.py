"""Portfolio performance chart rendering."""

from __future__ import annotations

import io
import logging

from analysis.performance_series import ChartPeriod, ValueBar, aggregate_performance_bars
from storage.models import PerformanceHistory

logger = logging.getLogger(__name__)

_PERIOD_TITLES: dict[ChartPeriod, str] = {
    "week": "Portfolio value — last 7 days (daily)",
    "month": "Portfolio value — last month (weekly)",
    "all": "Portfolio value — all time",
}


def render_performance_chart_png(
    history: PerformanceHistory,
    *,
    period: ChartPeriod = "week",
    timezone: str = "Asia/Hong_Kong",
) -> bytes | None:
    """Render aggregated OHLC candles plus a close line as a PNG image."""
    bars = aggregate_performance_bars(
        history.snapshots,
        period=period,
        timezone=timezone,
    )
    if len(bars) < 2:
        return None

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        logger.warning("matplotlib is not installed; skipping performance chart")
        return None

    figure, axis = plt.subplots(figsize=(8, 4.5), dpi=120)
    try:
        _draw_candle_line_chart(axis, bars)
        axis.set_title(_PERIOD_TITLES.get(period, "Portfolio value (HKD)"))
        axis.set_xlabel("Period")
        axis.set_ylabel("Total value (HKD)")
        axis.grid(True, linestyle="--", alpha=0.35)
        axis.set_xticks(range(len(bars)))
        axis.set_xticklabels([bar.label for bar in bars], rotation=25, ha="right")
        figure.tight_layout()

        buffer = io.BytesIO()
        figure.savefig(buffer, format="png", bbox_inches="tight")
        buffer.seek(0)
        return buffer.getvalue()
    finally:
        plt.close(figure)


def _draw_candle_line_chart(axis, bars: list[ValueBar]) -> None:
    """Draw candlesticks for OHLC and overlay the close series."""
    from matplotlib.patches import Rectangle

    xs = list(range(len(bars)))
    closes = [bar.close for bar in bars]
    span = max(closes) - min(closes)
    body_floor = span * 0.004 if span > 0 else max(closes[0], 1.0) * 0.0005

    for index, bar in enumerate(bars):
        rising = bar.close >= bar.open
        color = "#16a34a" if rising else "#dc2626"
        axis.vlines(index, bar.low, bar.high, color=color, linewidth=1.2, zorder=2)
        bottom = min(bar.open, bar.close)
        height = abs(bar.close - bar.open)
        if height < body_floor:
            height = body_floor
            bottom = bar.close - height / 2.0
        axis.add_patch(
            Rectangle(
                (index - 0.32, bottom),
                0.64,
                height,
                facecolor=color,
                edgecolor=color,
                alpha=0.85,
                zorder=3,
            )
        )

    axis.plot(
        xs,
        closes,
        color="#2563eb",
        linewidth=2.0,
        marker="o",
        markersize=5,
        zorder=4,
        label="Close",
    )
    axis.legend(loc="upper left", fontsize=8)
