"""Message formatting helpers for Telegram delivery."""

from storage.models import PendingAlert


def format_alert(alert: PendingAlert) -> str:
    """Render a pending alert as a Telegram-friendly message."""
    tickers = ", ".join(alert.related_tickers) if alert.related_tickers else "n/a"
    return (
        f"[{alert.severity.upper()}] {alert.message}\n"
        f"Tickers: {tickers}"
    )
