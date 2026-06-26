"""Telegram update handlers.

Each /command handler follows the same pattern:
  1. _guard() — reject messages from chats not in users.json
  2. BotCommands — load data, run analysis, format text
  3. reply_text() — send the response back to the user
"""

from __future__ import annotations

import logging
from io import BytesIO

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from bot.add_ticker_args import parse_add_ticker_args
from bot.commands import BotCommands
from bot.deposit_cash_args import parse_deposit_cash_args
from bot.dev_menu import DEV_MENU_CALLBACK_PREFIX, dev_menu_usage_key
from bot.developer_portfolio import CALLBACK_PREFIX, DeveloperActionReply
from bot.formatter import truncate_message
from bot.i18n import normalize_language, t
from bot.menu import main_menu_keyboard, setup_user_telegram_menu
from bot.sell_args import parse_sell_args
from bot.strategy_args import parse_strategy_add_args
from storage.models import BotUser, UserRole
from storage.portfolio_ops import portfolio_has_ticker
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
    if user is None:
        return None
    if user.role == "developer":
        return user
    if update.message is not None:
        await update.message.reply_text(t("command_unavailable", user.language))
    return None


async def _guard_developer_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> BotUser | None:
    """Developer guard for inline button callbacks."""
    repository = _repository(context)
    if update.effective_chat is None:
        return None
    user = repository.find_user(update.effective_chat.id)
    if user is None:
        return None
    if user.role == "developer":
        return user
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


async def _reply_command_usage(
    update: Update,
    user: BotUser,
    usage_key: str,
    *,
    error_key: str | None = None,
) -> None:
    """Show full command usage, optionally prefixed with a short validation error."""
    if error_key is not None and error_key != usage_key:
        text = f"{t(error_key, user.language)}\n\n{t(usage_key, user.language)}"
    else:
        text = t(usage_key, user.language)
    await _reply_with_menu(update, text, user=user)


async def _reply_developer_action(
    update: Update,
    reply: DeveloperActionReply,
    *,
    user: BotUser,
) -> None:
    """Send a developer action response with optional inline confirm/undo buttons."""
    if update.message is None:
        return
    is_developer = user.role == "developer"
    await update.message.reply_text(
        reply.text,
        reply_markup=reply.reply_markup,
    )
    if reply.reply_markup is None:
        await update.message.reply_text(
            t("menu_hint_dev", user.language) if is_developer else t("menu_hint", user.language),
            reply_markup=main_menu_keyboard(is_developer=is_developer),
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


async def performance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /performance — returns, drawdown, and portfolio value chart."""
    user = await _guard(update, context)
    if user is None or update.message is None:
        return

    commands = _commands(context)
    await update.message.reply_text(commands.performance_message(user.chat_id))
    chart = commands.performance_chart_png()
    if chart is not None:
        await update.message.reply_photo(photo=BytesIO(chart))


async def risk_metrics_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /risk_metrics — Sharpe, drawdown, and benchmark comparison."""
    user = await _guard(update, context)
    if user is None or update.message is None:
        return

    await update.message.reply_text(t("risk_metrics_fetching", user.language))
    await update.message.reply_text(
        _commands(context).risk_metrics_message(user.chat_id)
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
    """Handle /news_summary — refresh news, then stream LLM summaries."""
    user = await _guard(update, context)
    if user is None or update.message is None:
        return

    await update.message.reply_text(t("news_fetching", user.language))

    footer = t("news_footer", user.language)
    pending: str | None = None
    for message in _commands(context).iter_news_summary_messages(user.chat_id):
        if pending is not None:
            await update.message.reply_text(pending)
        pending = message

    if pending is None:
        return
    await update.message.reply_text(truncate_message(f"{pending}\n\n{footer}"))


async def portfolio_action_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle inline Confirm / Cancel / Undo buttons for developer portfolio edits."""
    query = update.callback_query
    if query is None or query.data is None:
        return

    user = await _guard_developer_callback(update, context)
    if user is None:
        await query.answer()
        return

    parts = query.data.split(":", 2)
    if len(parts) != 3 or parts[0] != CALLBACK_PREFIX:
        await query.answer()
        return

    _, action_name, action_id = parts
    commands = _commands(context)
    if action_name == "confirm":
        reply = commands.confirm_developer_portfolio_action(user.chat_id, action_id)
    elif action_name == "cancel":
        reply = commands.cancel_developer_portfolio_action(user.chat_id, action_id)
    elif action_name == "undo":
        reply = commands.undo_developer_portfolio_action(user.chat_id, action_id)
    else:
        await query.answer()
        return

    await query.answer()
    if query.message is not None:
        await query.message.reply_text(
            reply.text,
            reply_markup=reply.reply_markup,
        )
        if reply.reply_markup is None:
            await query.message.reply_text(
                t("menu_hint_dev", user.language),
                reply_markup=main_menu_keyboard(is_developer=True),
            )


def _parse_strategy_add_args(
    args: list[str],
    *,
    ticker_already_held: bool,
):
    """Backward-compatible wrapper for strategy argument parsing tests."""
    result, _error = parse_strategy_add_args(
        args,
        ticker_already_held=ticker_already_held,
    )
    if result is None:
        return None
    return result.ticker, result.shares, result.reasoning


async def strategy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /strategy — show investment ideas for holdings."""
    user = await _guard(update, context)
    if user is None or update.message is None:
        return

    args = context.args or []
    if args and args[0].lower() in {"help", "?", "usage"}:
        await _reply_command_usage(update, user, "strategy_usage")
        return

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
    if not args or (len(args) == 1 and args[0].lower() in {"help", "?", "usage"}):
        await _reply_command_usage(update, user, "add_ticker_strategy_usage")
        return

    ticker_already_held = portfolio_has_ticker(
        _repository(context).load_portfolio(),
        args[0],
    )
    parsed, error_key = parse_strategy_add_args(
        args,
        ticker_already_held=ticker_already_held,
    )
    if error_key is not None:
        await _reply_command_usage(
            update,
            user,
            "add_ticker_strategy_usage",
            error_key=error_key,
        )
        return
    if parsed is None:
        await _reply_command_usage(update, user, "add_ticker_strategy_usage")
        return

    if parsed.shares is not None and parsed.shares <= 0:
        await _reply_command_usage(
            update,
            user,
            "add_ticker_strategy_usage",
            error_key="add_ticker_strategy_shares_invalid",
        )
        return

    message = _commands(context).add_ticker_strategy_message(
        user.chat_id,
        parsed.ticker,
        parsed.holding_horizon,
        parsed.shares,
        parsed.reasoning,
        cost_basis=parsed.cost_basis,
    )
    await _reply_with_menu(update, message, user=user)


async def edit_strategy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /edit_strategy — hard-overwrite stored strategy text."""
    user = await _guard_developer(update, context)
    if user is None:
        return

    args = context.args or []
    if not args or (len(args) == 1 and args[0].lower() in {"help", "?", "usage"}):
        await _reply_command_usage(update, user, "edit_strategy_usage")
        return
    if len(args) < 2:
        await _reply_command_usage(update, user, "edit_strategy_usage")
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
    if not args or (len(args) == 1 and args[0].lower() in {"help", "?", "usage"}):
        await _reply_command_usage(update, user, "add_ticker_usage")
        return

    parsed, error_key = parse_add_ticker_args(args)
    if error_key is not None:
        await _reply_command_usage(
            update,
            user,
            "add_ticker_usage",
            error_key=error_key,
        )
        return
    if parsed is None:
        await _reply_command_usage(update, user, "add_ticker_usage")
        return

    message = _commands(context).add_ticker_message(
        user.chat_id,
        parsed.ticker,
        shares=parsed.shares,
        cost_basis=parsed.cost_basis,
    )
    await _reply_developer_action(update, message, user=user)


async def deposit_cash_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /deposit_cash — credit cash to the portfolio (developer only)."""
    user = await _guard_developer(update, context)
    if user is None:
        return

    args = context.args or []
    if not args or (len(args) == 1 and args[0].lower() in {"help", "?", "usage"}):
        await _reply_command_usage(update, user, "deposit_cash_usage")
        return

    parsed, error_key = parse_deposit_cash_args(args)
    if error_key is not None:
        await _reply_command_usage(
            update,
            user,
            "deposit_cash_usage",
            error_key=error_key,
        )
        return
    if parsed is None:
        await _reply_command_usage(update, user, "deposit_cash_usage")
        return

    reply = _commands(context).deposit_cash_message(
        user.chat_id,
        parsed.amount,
        currency=parsed.currency,
        note=parsed.note,
    )
    await _reply_developer_action(update, reply, user=user)


async def dev_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /dev_menu — inline hub for developer portfolio edits."""
    user = await _guard_developer(update, context)
    if user is None:
        return

    reply = _commands(context).dev_menu_message(user.chat_id)
    await _reply_developer_action(update, reply, user=user)


async def dev_menu_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle inline buttons from /dev_menu."""
    query = update.callback_query
    if query is None or query.data is None:
        return

    user = await _guard_developer_callback(update, context)
    if user is None:
        await query.answer()
        return

    parts = query.data.split(":", 2)
    if len(parts) != 3 or parts[0] != DEV_MENU_CALLBACK_PREFIX:
        await query.answer()
        return

    _, action_kind, action_name = parts
    await query.answer()

    if action_kind == "run" and action_name == "undo":
        reply = _commands(context).undo_last_portfolio_action_message(user.chat_id)
        if reply.text == t("portfolio_action_nothing_to_undo", user.language):
            text = (
                f"{t('portfolio_action_nothing_to_undo', user.language)}\n\n"
                f"{t('undo_usage', user.language)}"
            )
        else:
            text = reply.text
        if query.message is not None:
            await query.message.reply_text(
                text,
                reply_markup=reply.reply_markup,
            )
        return

    if action_kind == "usage":
        usage_key = dev_menu_usage_key(action_name)
        if usage_key is None:
            return
        if query.message is not None:
            await query.message.reply_text(t(usage_key, user.language))
        return


async def remove_ticker_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /remove_ticker — remove a holding (developer only)."""
    user = await _guard_developer(update, context)
    if user is None:
        return

    args = context.args or []
    if not args or (len(args) == 1 and args[0].lower() in {"help", "?", "usage"}):
        await _reply_command_usage(update, user, "remove_ticker_usage")
        return

    message = _commands(context).remove_ticker_message(user.chat_id, args[0])
    await _reply_developer_action(update, message, user=user)


async def sell_ticker_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /sell_ticker — preview a sell and wait for developer confirmation."""
    user = await _guard_developer(update, context)
    if user is None:
        return

    args = context.args or []
    if not args or (len(args) == 1 and args[0].lower() in {"help", "?", "usage"}):
        await _reply_command_usage(update, user, "sell_ticker_usage")
        return

    portfolio = _repository(context).load_portfolio()
    parsed, error_key = parse_sell_args(args, portfolio)
    if error_key is not None:
        await _reply_command_usage(
            update,
            user,
            "sell_ticker_usage",
            error_key=error_key,
        )
        return
    if parsed is None:
        await _reply_command_usage(update, user, "sell_ticker_usage")
        return

    reply = _commands(context).prepare_sell_ticker(user.chat_id, parsed)
    await _reply_developer_action(update, reply, user=user)


async def undo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /undo — reverse the last completed portfolio notification."""
    user = await _guard_developer(update, context)
    if user is None:
        return

    args = context.args or []
    if args and args[0].lower() in {"help", "?", "usage"}:
        await _reply_command_usage(update, user, "undo_usage")
        return

    reply = _commands(context).undo_last_portfolio_action_message(user.chat_id)
    if reply.text == t("portfolio_action_nothing_to_undo", user.language):
        await _reply_command_usage(
            update,
            user,
            "undo_usage",
            error_key="portfolio_action_nothing_to_undo",
        )
        return
    await _reply_developer_action(update, reply, user=user)


async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /analyze [pros] [ticker]."""
    user = await _guard(update, context)
    if user is None or update.message is None:
        return

    commands = _commands(context)
    raw_args = list(context.args or [])
    if raw_args and raw_args[0].lower() in {"help", "?", "usage"}:
        await _reply_command_usage(update, user, "analyze_usage")
        return

    pros_mode = False
    if raw_args and raw_args[0].lower() in {"pros", "--pros", "-pros"}:
        pros_mode = True
        raw_args = raw_args[1:]
    elif raw_args and raw_args[-1].lower() in {"pros", "--pros", "-pros"}:
        pros_mode = True
        raw_args = raw_args[:-1]

    ticker = raw_args[0] if raw_args else None
    if pros_mode:
        message = commands.analyze_pros_message(user.chat_id, ticker=ticker)
    elif ticker:
        message = commands.analyze_ticker_message(user.chat_id, ticker)
    else:
        message = commands.analyze_message(user.chat_id)
    await update.message.reply_text(message)


async def set_language_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /set_language — update the user's language preference."""
    user = await _guard(update, context)
    if user is None:
        return

    args = context.args or []
    if args and args[0].lower() in {"help", "?", "usage"}:
        await _reply_command_usage(update, user, "language_usage")
        return
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


async def ta_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /ta <TICKER> — technical analysis snapshot (developer only)."""
    user = await _guard_developer(update, context)
    if user is None or update.message is None:
        return

    args = context.args or []
    if not args or args[0].lower() in {"help", "?", "usage"}:
        await _reply_command_usage(update, user, "ta_usage")
        return

    await update.message.reply_text(t("ta_fetching", user.language))
    message, use_markdown = _commands(context).ta_message(user.chat_id, args[0])
    if use_markdown:
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN_V2)
    else:
        await update.message.reply_text(message)


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
    if not args or (len(args) == 1 and args[0].lower() in {"help", "?", "usage"}):
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
    if not args or (len(args) == 1 and args[0].lower() in {"help", "?", "usage"}):
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
        ("performance", performance_command),
        ("risk_metrics", risk_metrics_command),
        ("strategy", strategy_command),
        ("industries", industries_command),
        ("news_summary", news_summary_command),
        ("add_ticker", add_ticker_command),
        ("add_ticker_strategy", add_ticker_strategy_command),
        ("edit_strategy", edit_strategy_command),
        ("remove_ticker", remove_ticker_command),
        ("deposit_cash", deposit_cash_command),
        ("dev_menu", dev_menu_command),
        ("sell_ticker", sell_ticker_command),
        ("undo", undo_command),
        ("analyze", analyze_command),
        ("set_language", set_language_command),
        ("reload_config", reload_config_command),
        ("debug_state", debug_state_command),
        ("ta", ta_command),
        ("list_users", list_users_command),
        ("add_user", add_user_command),
        ("remove_user", remove_user_command),
    )
    for name, handler in command_handlers:
        application.add_handler(CommandHandler(name, handler))

    application.add_handler(
        CallbackQueryHandler(portfolio_action_callback, pattern=rf"^{CALLBACK_PREFIX}:")
    )
    application.add_handler(
        CallbackQueryHandler(dev_menu_callback, pattern=rf"^{DEV_MENU_CALLBACK_PREFIX}:")
    )

    logger.info(
        "Registered Telegram commands: %s",
        ", ".join(f"/{name}" for name, _ in command_handlers),
    )
