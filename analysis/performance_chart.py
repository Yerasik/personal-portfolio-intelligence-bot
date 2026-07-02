"""Portfolio performance chart rendering."""

from __future__ import annotations

import io
import logging

from analysis.performance_series import ChartPeriod, ValueBar, aggregate_performance_bars
from storage.models import PerformanceHistory

logger = logging.getLogger(__name__)

_PERIOD_SUBTITLES: dict[ChartPeriod, str] = {
    "week": "Last 7 days · one candle per day",
    "month": "Last 30 days · one candle per week",
    "all": "Full history · auto daily / weekly / monthly",
}

_STYLE = {
    "bg": "#f8fafc",
    "grid": "#e2e8f0",
    "text": "#0f172a",
    "muted": "#64748b",
    "up_fill": "#22c55e",
    "up_edge": "#15803d",
    "down_fill": "#fecaca",
    "down_edge": "#dc2626",
    "line": "#2563eb",
    "line_glow": "#93c5fd",
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
        from matplotlib.ticker import FuncFormatter
    except ImportError:
        logger.warning("matplotlib is not installed; skipping performance chart")
        return None

    figure, axis = plt.subplots(figsize=(9.5, 5.2), dpi=144)
    figure.patch.set_facecolor(_STYLE["bg"])
    axis.set_facecolor(_STYLE["bg"])

    try:
        _draw_candle_line_chart(axis, bars)
        _style_axes(axis, bars, period=period, timezone=timezone)

        axis.yaxis.set_major_formatter(FuncFormatter(_format_hkd_axis))
        figure.subplots_adjust(left=0.10, right=0.97, top=0.82, bottom=0.18)

        buffer = io.BytesIO()
        figure.savefig(
            buffer,
            format="png",
            bbox_inches="tight",
            facecolor=figure.get_facecolor(),
        )
        buffer.seek(0)
        return buffer.getvalue()
    finally:
        plt.close(figure)


def _style_axes(
    axis,
    bars: list[ValueBar],
    *,
    period: ChartPeriod,
    timezone: str,
) -> None:
    """Apply titles, labels, grid, and value padding."""
    first_close = bars[0].close
    last_close = bars[-1].close
    change_pct = ((last_close - first_close) / first_close * 100.0) if first_close > 0 else 0.0
    change_text = f"{change_pct:+.1f}%"
    change_color = _STYLE["up_edge"] if change_pct >= 0 else _STYLE["down_edge"]

    last_local = bars[-1].period_start
    updated = last_local.strftime("%-d %b %Y") if last_local else ""

    axis.set_title(
        "Portfolio value",
        loc="left",
        fontsize=15,
        fontweight="bold",
        color=_STYLE["text"],
        pad=12,
    )
    axis.text(
        0.0,
        1.02,
        _PERIOD_SUBTITLES.get(period, ""),
        transform=axis.transAxes,
        fontsize=9.5,
        color=_STYLE["muted"],
        va="bottom",
    )
    axis.text(
        0.99,
        1.02,
        f"{change_text}  ·  {_format_hkd_compact(last_close)}",
        transform=axis.transAxes,
        fontsize=11,
        fontweight="bold",
        color=change_color,
        ha="right",
        va="bottom",
    )
    if updated:
        axis.text(
            0.99,
            -0.14,
            f"Latest close · {updated} ({timezone})",
            transform=axis.transAxes,
            fontsize=8,
            color=_STYLE["muted"],
            ha="right",
        )

    axis.set_xticks(range(len(bars)))
    axis.set_xticklabels(
        [bar.label for bar in bars],
        fontsize=9,
        color=_STYLE["text"],
        linespacing=1.15,
    )
    axis.tick_params(axis="x", length=0, pad=6)
    axis.tick_params(axis="y", labelsize=9, colors=_STYLE["muted"])

    values = [bar.high for bar in bars] + [bar.low for bar in bars]
    ymin, ymax = min(values), max(values)
    padding = max((ymax - ymin) * 0.12, ymax * 0.01)
    axis.set_ylim(ymin - padding, ymax + padding)
    axis.set_xlim(-0.6, len(bars) - 0.4)

    axis.grid(axis="y", color=_STYLE["grid"], linestyle="-", linewidth=0.8, alpha=0.9)
    axis.grid(axis="x", visible=False)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.spines["left"].set_color(_STYLE["grid"])
    axis.spines["bottom"].set_color(_STYLE["grid"])


def _draw_candle_line_chart(axis, bars: list[ValueBar]) -> None:
    """Draw candlesticks for OHLC and overlay the close series."""
    from matplotlib.patches import Rectangle

    xs = list(range(len(bars)))
    closes = [bar.close for bar in bars]
    span = max(closes) - min(closes)
    body_floor = span * 0.006 if span > 0 else max(closes[0], 1.0) * 0.0008
    body_width = 0.55 if len(bars) <= 8 else 0.72

    for index, bar in enumerate(bars):
        rising = bar.close >= bar.open
        fill = _STYLE["up_fill"] if rising else _STYLE["down_fill"]
        edge = _STYLE["up_edge"] if rising else _STYLE["down_edge"]
        axis.vlines(
            index,
            bar.low,
            bar.high,
            color=edge,
            linewidth=1.4,
            zorder=2,
            alpha=0.95,
        )
        bottom = min(bar.open, bar.close)
        height = abs(bar.close - bar.open)
        if height < body_floor:
            height = body_floor
            bottom = bar.close - height / 2.0
        axis.add_patch(
            Rectangle(
                (index - body_width / 2.0, bottom),
                body_width,
                height,
                facecolor=fill,
                edgecolor=edge,
                linewidth=1.2,
                zorder=3,
            )
        )

    axis.plot(
        xs,
        closes,
        color=_STYLE["line_glow"],
        linewidth=4.0,
        zorder=4,
        solid_capstyle="round",
    )
    axis.plot(
        xs,
        closes,
        color=_STYLE["line"],
        linewidth=2.2,
        marker="o",
        markersize=6,
        markerfacecolor="white",
        markeredgecolor=_STYLE["line"],
        markeredgewidth=1.8,
        zorder=5,
        label="Close",
    )

    axis.scatter(
        [len(bars) - 1],
        [closes[-1]],
        s=90,
        color=_STYLE["line"],
        edgecolors="white",
        linewidths=2,
        zorder=6,
    )


def _format_hkd_compact(value: float) -> str:
    """Compact HKD label for titles."""
    if value >= 1_000_000:
        return f"HK${value / 1_000_000:.2f}M"
    if value >= 10_000:
        return f"HK${value / 1_000:.1f}k"
    return f"HK${value:,.0f}"


def _format_hkd_axis(value: float, _position: int) -> str:
    """Y-axis tick formatter."""
    return _format_hkd_compact(value)
