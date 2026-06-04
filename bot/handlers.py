"""Telegram update handlers (to be wired in a later iteration)."""

from telegram.ext import Application


def register_handlers(application: Application) -> None:
    """Register command and callback handlers on the Telegram application."""
    _ = application
