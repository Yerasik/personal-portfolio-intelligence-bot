"""Telegram command menu and reply keyboard."""

from __future__ import annotations

import logging

from telegram import BotCommand, BotCommandScopeChat, BotCommandScopeDefault, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import Application

logger = logging.getLogger(__name__)

ORDINARY_BOT_COMMANDS: tuple[BotCommand, ...] = (
    BotCommand("start", "Welcome and show the menu"),
    BotCommand("menu", "Show the tap-to-run menu"),
    BotCommand("help", "List all commands"),
    BotCommand("portfolio", "Holdings and latest prices"),
    BotCommand("strategy", "Investment idea behind each holding"),
    BotCommand("industries", "Focus industries and news counts"),
    BotCommand("news_summary", "LLM news by sector and ticker"),
    BotCommand("analyze", "Portfolio advisory or /analyze AAPL"),
    BotCommand("set_language", "Set your language (en, de, zh, ru)"),
)

DEVELOPER_BOT_COMMANDS: tuple[BotCommand, ...] = ORDINARY_BOT_COMMANDS + (
    BotCommand("add_ticker", "Add shares (new or existing holding)"),
    BotCommand("add_ticker_strategy", "Add holding with investment idea"),
    BotCommand("edit_strategy", "Rewrite a stored investment idea"),
    BotCommand("remove_ticker", "Remove a holding from the portfolio"),
    BotCommand("sell_ticker", "Sell shares at a price and notify users"),
    BotCommand("list_users", "List authorized users"),
    BotCommand("add_user", "Authorize a Telegram user"),
    BotCommand("remove_user", "Revoke user access"),
    BotCommand("reload_config", "Reload config.json from disk"),
    BotCommand("debug_state", "Show internal runtime counters"),
)

# Default slash menu for any chat without a per-user override.
TELEGRAM_BOT_COMMANDS = ORDINARY_BOT_COMMANDS


def main_menu_keyboard(*, is_developer: bool = False) -> ReplyKeyboardMarkup:
    """Persistent reply keyboard; developers get portfolio-edit and user-management buttons."""
    rows = [
        [KeyboardButton("/portfolio"), KeyboardButton("/strategy")],
        [KeyboardButton("/industries"), KeyboardButton("/news_summary")],
        [KeyboardButton("/analyze"), KeyboardButton("/set_language")],
        [KeyboardButton("/help"), KeyboardButton("/menu")],
    ]
    if is_developer:
        rows.insert(
            2,
            [
                KeyboardButton("/add_ticker_strategy"),
                KeyboardButton("/edit_strategy"),
            ],
        )
        rows.insert(
            3,
            [
                KeyboardButton("/add_ticker"),
                KeyboardButton("/remove_ticker"),
                KeyboardButton("/sell_ticker"),
            ],
        )
        rows.extend(
            [
                [KeyboardButton("/list_users")],
                [KeyboardButton("/add_user"), KeyboardButton("/remove_user")],
            ]
        )
    return ReplyKeyboardMarkup(
        rows,
        resize_keyboard=True,
        is_persistent=True,
    )


async def setup_telegram_menu(application: Application) -> None:
    """Register default slash commands visible to all users."""
    await application.bot.set_my_commands(
        list(ORDINARY_BOT_COMMANDS),
        scope=BotCommandScopeDefault(),
    )
    logger.info(
        "Telegram default command menu updated: %s",
        ", ".join(f"/{cmd.command}" for cmd in ORDINARY_BOT_COMMANDS),
    )


async def setup_developer_telegram_menu(application: Application, chat_id: int) -> None:
    """Register extended slash commands for one developer chat."""
    await application.bot.set_my_commands(
        list(DEVELOPER_BOT_COMMANDS),
        scope=BotCommandScopeChat(chat_id=chat_id),
    )
    logger.info(
        "Telegram developer command menu updated for chat_id=%s",
        chat_id,
    )


async def setup_ordinary_telegram_menu(application: Application, chat_id: int) -> None:
    """Register the ordinary slash-command set for one authorized user."""
    await application.bot.set_my_commands(
        list(ORDINARY_BOT_COMMANDS),
        scope=BotCommandScopeChat(chat_id=chat_id),
    )
    logger.info(
        "Telegram ordinary command menu updated for chat_id=%s",
        chat_id,
    )


async def setup_user_telegram_menu(
    application: Application,
    *,
    chat_id: int,
    is_developer: bool,
) -> None:
    """Refresh slash commands for one chat based on role."""
    await setup_telegram_menu(application)
    if is_developer:
        await setup_developer_telegram_menu(application, chat_id)
    else:
        await setup_ordinary_telegram_menu(application, chat_id)
