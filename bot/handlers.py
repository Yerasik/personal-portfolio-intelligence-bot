"""Telegram update handlers.

Each /command handler follows the same pattern:
  1. _guard() — reject messages from chats other than TELEGRAM_CHAT_ID
  2. BotCommands — load data, run analysis, format text
  3. reply_text() — send the response back to the user
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from bot.commands import BotCommands
from bot.menu import main_menu_keyboard, setup_telegram_menu
from config.settings import RuntimeSettings

logger = logging.getLogger(__name__)


def _expected_chat_id(settings: RuntimeSettings) -> str:
    """Return the authorized chat id from env, normalized as a string."""
    return str(settings.telegram_chat_id).strip()


def is_authorized(update: Update, settings: RuntimeSettings) -> bool:
    """Return True when the update comes from the configured single-user chat."""
    if update.effective_chat is None:
        return False
    return str(update.effective_chat.id) == _expected_chat_id(settings)


async def _reject_unauthorized(update: Update) -> None:
    """Tell unknown users this bot is single-user only."""
    if update.message is None:
        return
    await update.message.reply_text(
        "This bot is restricted to a single authorized user."
    )


def _commands(context: ContextTypes.DEFAULT_TYPE) -> BotCommands:
    """Fetch the shared BotCommands instance stored in application.bot_data."""
    return context.application.bot_data["commands"]


def _settings(context: ContextTypes.DEFAULT_TYPE) -> RuntimeSettings:
    """Fetch runtime settings (token, chat id) from application.bot_data."""
    return context.application.bot_data["settings"]


async def _guard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Return True when the sender is authorized; otherwise reply and return False."""
    settings = _settings(context)
    if is_authorized(update, settings):
        return True
    chat_id = update.effective_chat.id if update.effective_chat else "unknown"
    logger.warning("Ignoring unauthorized Telegram chat_id=%s", chat_id)
    await _reject_unauthorized(update)
    return False


async def _reply_with_menu(
    update: Update,
    text: str,
    *,
    show_menu: bool = True,
) -> None:
    """Send a text reply and attach the main reply keyboard when requested."""
    if update.message is None:
        return
    await update.message.reply_text(
        text,
        reply_markup=main_menu_keyboard() if show_menu else None,
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start — send the welcome message."""
    if not await _guard(update, context):
        return
    await setup_telegram_menu(context.application)
    await _reply_with_menu(update, _commands(context).start_message())


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /menu — show the tap-to-run reply keyboard."""
    if not await _guard(update, context):
        return
    await setup_telegram_menu(context.application)
    await _reply_with_menu(
        update,
        "Choose an action from the menu below.\n\n"
        "Portfolio edits need a symbol, e.g.:\n"
        "/add_ticker AAPL 5\n"
        "/remove_ticker MSFT",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help — list available commands."""
    if not await _guard(update, context):
        return
    await _reply_with_menu(update, _commands(context).help_message())


async def portfolio_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /portfolio — show holdings and latest cached prices."""
    if not await _guard(update, context):
        return
    await update.message.reply_text(_commands(context).portfolio_message())


async def industries_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /industries — show focus industries and related news counts."""
    if not await _guard(update, context):
        return
    await update.message.reply_text(_commands(context).industries_message())


async def news_summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /news_summary — LLM summaries of cached news by sector and ticker."""
    if not await _guard(update, context):
        return
    await update.message.reply_text(_commands(context).news_summary_message())


_ADD_TICKER_USAGE = (
    "Usage: /add_ticker <SYMBOL> [shares]\n"
    "Adds shares to an existing holding or creates a new one.\n"
    "Example: /add_ticker AAPL\n"
    "Example: /add_ticker AAPL 5"
)
_REMOVE_TICKER_USAGE = (
    "Usage: /remove_ticker <SYMBOL>\n"
    "Example: /remove_ticker TSLA"
)


async def add_ticker_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /add_ticker — add a validated holding to portfolio.json."""
    if not await _guard(update, context):
        return

    args = context.args or []
    if not args:
        await _reply_with_menu(update, _ADD_TICKER_USAGE)
        return

    shares = 1.0
    if len(args) >= 2:
        try:
            shares = float(args[1])
        except ValueError:
            await _reply_with_menu(
                update,
                f"Invalid share count: {args[1]!r}\n\n{_ADD_TICKER_USAGE}",
            )
            return

    message = _commands(context).add_ticker_message(args[0], shares=shares)
    await _reply_with_menu(update, message)


async def remove_ticker_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /remove_ticker — remove a holding from portfolio.json."""
    if not await _guard(update, context):
        return

    args = context.args or []
    if not args:
        await _reply_with_menu(update, _REMOVE_TICKER_USAGE)
        return

    message = _commands(context).remove_ticker_message(args[0])
    await _reply_with_menu(update, message)


async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /analyze [ticker].

    With no argument, return the portfolio-wide advisory. With a ticker
    (e.g. /analyze AAPL), explain that ticker's recent price move.
    """
    if not await _guard(update, context):
        return

    commands = _commands(context)
    args = context.args or []
    if args:
        message = commands.analyze_ticker_message(args[0])
    else:
        message = commands.analyze_message()
    await update.message.reply_text(message)


def register_handlers(
    application: Application,
    commands: BotCommands,
    settings: RuntimeSettings,
) -> None:
    """Register command handlers on the Telegram application."""
    application.bot_data["commands"] = commands
    application.bot_data["settings"] = settings

    command_handlers = (
        ("start", start_command),
        ("menu", menu_command),
        ("help", help_command),
        ("portfolio", portfolio_command),
        ("industries", industries_command),
        ("news_summary", news_summary_command),
        ("add_ticker", add_ticker_command),
        ("remove_ticker", remove_ticker_command),
        ("analyze", analyze_command),
    )
    for name, handler in command_handlers:
        application.add_handler(CommandHandler(name, handler))

    logger.info(
        "Registered Telegram commands: %s",
        ", ".join(f"/{name}" for name, _ in command_handlers),
    )
