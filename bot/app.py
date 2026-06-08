"""Telegram application factory and runtime context.

build_bot_context() creates the python-telegram-bot Application, attaches
BotCommands + auth settings, and registers /command handlers.
"""

from dataclasses import dataclass

from telegram.ext import Application

from analysis.llm import LlmClient
from bot.commands import BotCommands
from bot.handlers import register_handlers
from bot.menu import setup_telegram_menu
from config.settings import RuntimeSettings
from storage.repository import DataRepository


@dataclass(frozen=True)
class BotContext:
    """Shared dependencies for Telegram handlers."""

    settings: RuntimeSettings
    repository: DataRepository
    commands: BotCommands
    application: Application


def build_bot_context(
    settings: RuntimeSettings,
    repository: DataRepository,
    llm: LlmClient,
) -> BotContext:
    """Construct a python-telegram-bot Application with handlers registered."""
    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(setup_telegram_menu)
        .build()
    )
    commands = BotCommands(repository=repository, llm=llm)
    register_handlers(application, commands, repository)
    return BotContext(
        settings=settings,
        repository=repository,
        commands=commands,
        application=application,
    )
