"""Portfolio performance chart rendering."""

from __future__ import annotations

import io
import logging
from datetime import UTC

from storage.models import PerformanceHistory

logger = logging.getLogger(__name__)


def render_performance_chart_png(history: PerformanceHistory) -> bytes | None:
    """Render portfolio total value over time as a PNG image."""
    snapshots = sorted(history.snapshots, key=lambda row: row.timestamp)
    if len(snapshots) < 2:
        return None

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
    except ImportError:
        logger.warning("matplotlib is not installed; skipping performance chart")
        return None

    timestamps = [
        row.timestamp.replace(tzinfo=UTC)
        if row.timestamp.tzinfo is None
        else row.timestamp
        for row in snapshots
    ]
    values = [row.total_value for row in snapshots]

    figure, axis = plt.subplots(figsize=(8, 4.5), dpi=120)
    try:
        axis.plot(timestamps, values, color="#2563eb", linewidth=2.0, marker="o", markersize=3)
        axis.fill_between(timestamps, values, alpha=0.12, color="#2563eb")
        axis.set_title("Portfolio value (HKD)")
        axis.set_xlabel("Time (UTC)")
        axis.set_ylabel("Total value")
        axis.grid(True, linestyle="--", alpha=0.35)
        axis.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
        figure.autofmt_xdate(rotation=25)
        figure.tight_layout()

        buffer = io.BytesIO()
        figure.savefig(buffer, format="png", bbox_inches="tight")
        buffer.seek(0)
        return buffer.getvalue()
    finally:
        plt.close(figure)
