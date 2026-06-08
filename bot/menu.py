"""Telegram command menu and reply keyboard."""

from __future__ import annotations

import logging

from telegram import BotCommand, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import Application

logger = logging.getLogger(__name__)

TELEGRAM_BOT_COMMANDS: tuple[BotCommand, ...] = (
    BotCommand("start", "Welcome and show the menu"),
    BotCommand("menu", "Show the tap-to-run menu"),
    BotCommand("help", "List all commands"),
    BotCommand("portfolio", "Holdings and latest prices"),
    BotCommand("industries", "Focus industries and news counts"),
    BotCommand("news_summary", "LLM news by sector and ticker"),
    BotCommand("add_ticker", "Add shares (new or existing holding)"),
    BotCommand("remove_ticker", "Remove a holding from the portfolio"),
    BotCommand("analyze", "Portfolio advisory or /analyze AAPL"),
)


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Persistent reply keyboard with the main bot actions."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("/portfolio"), KeyboardButton("/industries")],
            [KeyboardButton("/news_summary"), KeyboardButton("/analyze")],
            [KeyboardButton("/add_ticker"), KeyboardButton("/remove_ticker")],
            [KeyboardButton("/help"), KeyboardButton("/menu")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


async def setup_telegram_menu(application: Application) -> None:
    """Register slash commands with Telegram so they appear in the client menu."""
    await application.bot.set_my_commands(list(TELEGRAM_BOT_COMMANDS))
    logger.info(
        "Telegram command menu updated: %s",
        ", ".join(f"/{cmd.command}" for cmd in TELEGRAM_BOT_COMMANDS),
    )
