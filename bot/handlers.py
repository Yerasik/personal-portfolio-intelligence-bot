"""Telegram update handlers.

Each /command handler follows the same pattern:
  1. _guard() — reject messages from chats not in users.json
  2. BotCommands — load data, run analysis, format text
  3. reply_text() — send the response back to the user
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from bot.commands import BotCommands
from bot.formatter import truncate_message
from bot.i18n import normalize_language, t
from bot.menu import main_menu_keyboard, setup_user_telegram_menu
from storage.models import BotUser, UserRole
from storage.repository import DataRepository

logger = logging.getLogger(__name__)


def is_authorized(update: Update, repository: DataRepository) -> bool:
    """Return True when the update comes from an authorized user."""
    if update.effective_chat is None:
        return False
    return repository.is_authorized_user(update.effective_chat.id)


def _repository(context: ContextTypes.DEFAULT_TYPE) -> DataRepository:
    """Fetch the shared DataRepository from application.bot_data."""
    return context.application.bot_data["repository"]


def _commands(context: ContextTypes.DEFAULT_TYPE) -> BotCommands:
    """Fetch the shared BotCommands instance stored in application.bot_data."""
    return context.application.bot_data["commands"]


def _fallback_lang(update: Update) -> str:
    """Guess language from Telegram profile when user record is unavailable."""
    if update.effective_user and update.effective_user.language_code:
        return normalize_language(update.effective_user.language_code)
    return "en"


async def _reject_unauthorized(update: Update) -> None:
    """Tell unknown users this bot is restricted."""
    if update.message is None:
        return
    await update.message.reply_text(t("unauthorized", _fallback_lang(update)))


async def _guard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> BotUser | None:
    """Return the authorized user or reply and return None."""
    repository = _repository(context)
    if update.effective_chat is None:
        return None
    user = repository.find_user(update.effective_chat.id)
    if user is not None:
        return user
    logger.warning(
        "Ignoring unauthorized Telegram chat_id=%s",
        update.effective_chat.id,
    )
    await _reject_unauthorized(update)
    return None


async def _guard_developer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> BotUser | None:
    """Return the user when they have the developer role."""
    user = await _guard(update, context)
    if user is None or update.message is None:
        return None
    if user.role == "developer":
        return user
    await update.message.reply_text(t("command_unavailable", user.language))
    return None


def _menu_hint(user: BotUser) -> str:
    """Return the menu hint text for ordinary or developer users."""
    if user.role == "developer":
        return t("menu_hint_dev", user.language)
    return t("menu_hint", user.language)


async def _reply_with_menu(
    update: Update,
    text: str,
    *,
    user: BotUser | None = None,
    show_menu: bool = True,
) -> None:
    """Send a text reply and attach the role-appropriate reply keyboard."""
    if update.message is None:
        return
    is_developer = user is not None and user.role == "developer"
    await update.message.reply_text(
        text,
        reply_markup=main_menu_keyboard(is_developer=is_developer) if show_menu else None,
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start — send the welcome message."""
    user = await _guard(update, context)
    if user is None:
        return
    await setup_user_telegram_menu(
        context.application,
        chat_id=user.chat_id,
        is_developer=user.role == "developer",
    )
    await _reply_with_menu(
        update,
        _commands(context).start_message(user.chat_id),
        user=user,
    )


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /menu — show the tap-to-run reply keyboard."""
    user = await _guard(update, context)
    if user is None:
        return
    await setup_user_telegram_menu(
        context.application,
        chat_id=user.chat_id,
        is_developer=user.role == "developer",
    )
    await _reply_with_menu(
        update,
        _menu_hint(user),
        user=user,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help — list available commands."""
    user = await _guard(update, context)
    if user is None:
        return
    await _reply_with_menu(
        update,
        _commands(context).help_message(user.chat_id),
        user=user,
    )


async def portfolio_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /portfolio — show holdings and latest cached prices."""
    user = await _guard(update, context)
    if user is None or update.message is None:
        return
    await update.message.reply_text(
        _commands(context).portfolio_message(user.chat_id)
    )


async def industries_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /industries — show focus industries and related news counts."""
    user = await _guard(update, context)
    if user is None or update.message is None:
        return
    await update.message.reply_text(
        _commands(context).industries_message(user.chat_id)
    )


async def news_summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /news_summary — stream LLM summaries as each group completes."""
    user = await _guard(update, context)
    if user is None or update.message is None:
        return

    footer = t("news_footer", user.language)
    pending: str | None = None
    for message in _commands(context).iter_news_summary_messages(user.chat_id):
        if pending is not None:
            await update.message.reply_text(pending)
        pending = message

    if pending is None:
        return
    await update.message.reply_text(truncate_message(f"{pending}\n\n{footer}"))


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


def _parse_strategy_add_args(args: list[str]) -> tuple[str, float, str] | None:
    """Parse /add_ticker_strategy <TICKER> [shares] <reasoning>."""
    if len(args) < 2:
        return None
    ticker = args[0]
    shares = 1.0
    reasoning_start = 1
    try:
        shares = float(args[1])
        reasoning_start = 2
    except ValueError:
        reasoning_start = 1
    reasoning = " ".join(args[reasoning_start:]).strip()
    if not reasoning:
        return None
    return ticker, shares, reasoning


async def strategy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /strategy — show investment ideas for holdings."""
    user = await _guard(update, context)
    if user is None or update.message is None:
        return

    args = context.args or []
    ticker = args[0] if args else None
    await update.message.reply_text(
        _commands(context).strategy_message(user.chat_id, ticker=ticker)
    )


async def add_ticker_strategy_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle /add_ticker_strategy — add a holding with developer reasoning."""
    user = await _guard_developer(update, context)
    if user is None:
        return

    args = context.args or []
    parsed = _parse_strategy_add_args(args)
    if parsed is None:
        await _reply_with_menu(
            update,
            t("add_ticker_strategy_usage", user.language),
            user=user,
        )
        return

    ticker, shares, reasoning = parsed
    if shares <= 0:
        await _reply_with_menu(
            update,
            f"Invalid share count.\n\n{t('add_ticker_strategy_usage', user.language)}",
            user=user,
        )
        return

    message = _commands(context).add_ticker_strategy_message(
        user.chat_id,
        ticker,
        shares,
        reasoning,
    )
    await _reply_with_menu(update, message, user=user)


async def edit_strategy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /edit_strategy — hard-overwrite stored strategy text."""
    user = await _guard_developer(update, context)
    if user is None:
        return

    args = context.args or []
    if len(args) < 2:
        await _reply_with_menu(
            update,
            t("edit_strategy_usage", user.language),
            user=user,
        )
        return

    ticker = args[0]
    strategy_text = " ".join(args[1:]).strip()
    message = _commands(context).edit_strategy_message(
        user.chat_id,
        ticker,
        strategy_text,
    )
    await _reply_with_menu(update, message, user=user)


async def add_ticker_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /add_ticker — add a validated holding (developer only)."""
    user = await _guard_developer(update, context)
    if user is None:
        return

    args = context.args or []
    if not args:
        await _reply_with_menu(update, _ADD_TICKER_USAGE, user=user)
        return

    shares = 1.0
    if len(args) >= 2:
        try:
            shares = float(args[1])
        except ValueError:
            await _reply_with_menu(
                update,
                f"Invalid share count: {args[1]!r}\n\n{_ADD_TICKER_USAGE}",
                user=user,
            )
            return

    message = _commands(context).add_ticker_message(user.chat_id, args[0], shares=shares)
    await _reply_with_menu(update, message, user=user)


async def remove_ticker_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /remove_ticker — remove a holding (developer only)."""
    user = await _guard_developer(update, context)
    if user is None:
        return

    args = context.args or []
    if not args:
        await _reply_with_menu(update, _REMOVE_TICKER_USAGE, user=user)
        return

    message = _commands(context).remove_ticker_message(user.chat_id, args[0])
    await _reply_with_menu(update, message, user=user)


async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /analyze [ticker]."""
    user = await _guard(update, context)
    if user is None or update.message is None:
        return

    commands = _commands(context)
    args = context.args or []
    if args:
        message = commands.analyze_ticker_message(user.chat_id, args[0])
    else:
        message = commands.analyze_message(user.chat_id)
    await update.message.reply_text(message)


async def set_language_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /set_language — update the user's language preference."""
    user = await _guard(update, context)
    if user is None:
        return

    args = context.args or []
    if not args:
        await _reply_with_menu(
            update,
            _commands(context).current_language_message(user.chat_id),
            user=user,
        )
        return

    message = _commands(context).set_language_message(user.chat_id, args[0])
    await _reply_with_menu(update, message, user=user)


async def reload_config_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /reload_config — reload config.json (developer only)."""
    user = await _guard_developer(update, context)
    if user is None:
        return
    await _reply_with_menu(
        update,
        _commands(context).reload_config_message(user.chat_id),
        show_menu=False,
    )


async def debug_state_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /debug_state — show internal counters (developer only)."""
    user = await _guard_developer(update, context)
    if user is None:
        return
    await _reply_with_menu(
        update,
        _commands(context).debug_state_message(user.chat_id),
        show_menu=False,
    )


async def list_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /list_users — show authorized users (developer only)."""
    user = await _guard_developer(update, context)
    if user is None:
        return
    await _reply_with_menu(
        update,
        _commands(context).list_users_message(user.chat_id),
        user=user,
    )


async def add_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /add_user — authorize a Telegram user (developer only)."""
    user = await _guard_developer(update, context)
    if user is None:
        return

    usage = t("add_user_usage", user.language)
    args = context.args or []
    if not args:
        await _reply_with_menu(update, usage, user=user)
        return

    try:
        target_chat_id = int(args[0])
    except ValueError:
        await _reply_with_menu(
            update,
            f"{t('add_user_invalid_id', user.language, value=args[0])}\n\n{usage}",
            user=user,
        )
        return

    role: UserRole = "ordinary"
    language = "en"
    if len(args) >= 2:
        role_candidate = args[1].strip().lower()
        if role_candidate in {"developer", "ordinary"}:
            role = role_candidate  # type: ignore[assignment]
        else:
            language = args[1]
    if len(args) >= 3:
        language = args[2]

    message = _commands(context).add_user_message(
        user.chat_id,
        target_chat_id,
        role=role,
        language=language,
    )
    await _reply_with_menu(update, message, user=user)


async def remove_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /remove_user — revoke user access (developer only)."""
    user = await _guard_developer(update, context)
    if user is None:
        return

    usage = t("remove_user_usage", user.language)
    args = context.args or []
    if not args:
        await _reply_with_menu(update, usage, user=user)
        return

    try:
        target_chat_id = int(args[0])
    except ValueError:
        await _reply_with_menu(
            update,
            f"{t('add_user_invalid_id', user.language, value=args[0])}\n\n{usage}",
            user=user,
        )
        return

    message = _commands(context).remove_user_message(user.chat_id, target_chat_id)
    await _reply_with_menu(update, message, user=user)


def register_handlers(
    application: Application,
    commands: BotCommands,
    repository: DataRepository,
) -> None:
    """Register command handlers on the Telegram application."""
    application.bot_data["commands"] = commands
    application.bot_data["repository"] = repository

    command_handlers = (
        ("start", start_command),
        ("menu", menu_command),
        ("help", help_command),
        ("portfolio", portfolio_command),
        ("strategy", strategy_command),
        ("industries", industries_command),
        ("news_summary", news_summary_command),
        ("add_ticker", add_ticker_command),
        ("add_ticker_strategy", add_ticker_strategy_command),
        ("edit_strategy", edit_strategy_command),
        ("remove_ticker", remove_ticker_command),
        ("analyze", analyze_command),
        ("set_language", set_language_command),
        ("reload_config", reload_config_command),
        ("debug_state", debug_state_command),
        ("list_users", list_users_command),
        ("add_user", add_user_command),
        ("remove_user", remove_user_command),
    )
    for name, handler in command_handlers:
        application.add_handler(CommandHandler(name, handler))

    logger.info(
        "Registered Telegram commands: %s",
        ", ".join(f"/{name}" for name, _ in command_handlers),
    )
