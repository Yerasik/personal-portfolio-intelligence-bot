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
    BotCommand("performance", "Returns, drawdown, and value chart"),
    BotCommand("risk_metrics", "Sharpe, drawdown, vs benchmark"),
    BotCommand("strategy", "Investment idea behind each holding"),
    BotCommand("industries", "Focus industries and news counts"),
    BotCommand("news_summary", "LLM news by sector and ticker"),
    BotCommand("analyze", "Portfolio advisory or /analyze AAPL"),
    BotCommand("set_language", "Set your language (en, de, zh, ru)"),
)

DEVELOPER_BOT_COMMANDS: tuple[BotCommand, ...] = ORDINARY_BOT_COMMANDS + (
    BotCommand("dev_menu", "Portfolio edits and admin (inline menu)"),
    BotCommand("deposit_cash", "Credit HKD, USD, or JPY cash"),
    BotCommand("add_ticker", "Add shares with optional per-share cost basis"),
    BotCommand(
        "add_ticker_strategy",
        "Add holding (long/short) with idea and optional cost basis",
    ),
    BotCommand("edit_strategy", "Rewrite a stored investment idea"),
    BotCommand("remove_ticker", "Remove a holding from the portfolio"),
    BotCommand("sell_ticker", "Sell at a price; confirm before users are notified"),
    BotCommand("undo", "Reverse the last portfolio notification"),
    BotCommand("list_users", "List authorized users"),
    BotCommand("add_user", "Authorize a Telegram user"),
    BotCommand("remove_user", "Revoke user access"),
    BotCommand("reload_config", "Reload config.json from disk"),
    BotCommand("debug_state", "Show internal runtime counters"),
    BotCommand("ta", "Technical analysis for one ticker"),
)

# Default slash menu for any chat without a per-user override.
TELEGRAM_BOT_COMMANDS = ORDINARY_BOT_COMMANDS


def main_menu_keyboard(*, is_developer: bool = False) -> ReplyKeyboardMarkup:
    """Persistent reply keyboard; developers get a compact row for cash + dev hub."""
    rows = [
        [KeyboardButton("/portfolio"), KeyboardButton("/performance")],
        [KeyboardButton("/analyze"), KeyboardButton("/risk_metrics")],
        [KeyboardButton("/strategy"), KeyboardButton("/news_summary")],
        [KeyboardButton("/industries"), KeyboardButton("/set_language")],
        [KeyboardButton("/help"), KeyboardButton("/menu")],
    ]
    if is_developer:
        rows.insert(
            3,
            [KeyboardButton("/deposit_cash"), KeyboardButton("/dev_menu")],
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
