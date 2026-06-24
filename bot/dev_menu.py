"""Developer portfolio edit menu (inline keyboard hub)."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.i18n import t

DEV_MENU_CALLBACK_PREFIX = "dmenu"

_DEV_MENU_USAGE_KEYS: dict[str, str] = {
    "add_ticker": "add_ticker_usage",
    "add_ticker_strategy": "add_ticker_strategy_usage",
    "sell_ticker": "sell_ticker_usage",
    "remove_ticker": "remove_ticker_usage",
    "deposit_cash": "deposit_cash_usage",
    "edit_strategy": "edit_strategy_usage",
    "undo": "undo_usage",
    "users": "dev_menu_users_usage",
    "diagnostics": "dev_menu_diagnostics_usage",
}


def dev_menu_usage_key(action: str) -> str | None:
    """Map a dev-menu action id to an i18n usage key."""
    return _DEV_MENU_USAGE_KEYS.get(action)


def dev_menu_inline_keyboard(*, lang: str) -> InlineKeyboardMarkup:
    """Inline keyboard grouping developer portfolio and admin commands."""
    prefix = DEV_MENU_CALLBACK_PREFIX
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("dev_menu_btn_add", lang),
                    callback_data=f"{prefix}:usage:add_ticker",
                ),
                InlineKeyboardButton(
                    t("dev_menu_btn_strategy", lang),
                    callback_data=f"{prefix}:usage:add_ticker_strategy",
                ),
            ],
            [
                InlineKeyboardButton(
                    t("dev_menu_btn_sell", lang),
                    callback_data=f"{prefix}:usage:sell_ticker",
                ),
                InlineKeyboardButton(
                    t("dev_menu_btn_remove", lang),
                    callback_data=f"{prefix}:usage:remove_ticker",
                ),
            ],
            [
                InlineKeyboardButton(
                    t("dev_menu_btn_deposit", lang),
                    callback_data=f"{prefix}:usage:deposit_cash",
                ),
                InlineKeyboardButton(
                    t("dev_menu_btn_undo", lang),
                    callback_data=f"{prefix}:run:undo",
                ),
            ],
            [
                InlineKeyboardButton(
                    t("dev_menu_btn_edit_strategy", lang),
                    callback_data=f"{prefix}:usage:edit_strategy",
                ),
                InlineKeyboardButton(
                    t("dev_menu_btn_users", lang),
                    callback_data=f"{prefix}:usage:users",
                ),
            ],
            [
                InlineKeyboardButton(
                    t("dev_menu_btn_diagnostics", lang),
                    callback_data=f"{prefix}:usage:diagnostics",
                ),
            ],
        ]
    )
