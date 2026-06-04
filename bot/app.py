"""Telegram application factory and runtime context."""

from dataclasses import dataclass

from telegram.ext import Application

from config.settings import RuntimeSettings
from storage.repository import DataRepository


@dataclass(frozen=True)
class BotContext:
    """Shared dependencies for future Telegram handlers."""

    settings: RuntimeSettings
    repository: DataRepository
    application: Application


def build_bot_context(
    settings: RuntimeSettings,
    repository: DataRepository,
) -> BotContext:
    """Construct a python-telegram-bot Application without registering handlers."""
    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .build()
    )
    return BotContext(
        settings=settings,
        repository=repository,
        application=application,
    )
