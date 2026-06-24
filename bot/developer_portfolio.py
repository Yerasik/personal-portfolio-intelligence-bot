"""Developer portfolio confirm/undo helpers and Telegram inline keyboards."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from storage.models import DeveloperPortfolioAction, Portfolio, TickerStrategy
from storage.portfolio_ops import normalize_ticker
from storage.repository import DataRepository

CALLBACK_PREFIX = "pdev"


@dataclass(frozen=True)
class DeveloperActionReply:
    """Text response plus optional inline keyboard for confirm or undo."""

    text: str
    reply_markup: InlineKeyboardMarkup | None = None


def new_action_id() -> str:
    """Return a short unique id for callback_data payloads."""
    return uuid.uuid4().hex[:12]


def confirm_keyboard(action_id: str, *, confirm_label: str, cancel_label: str) -> InlineKeyboardMarkup:
    """Inline keyboard shown before a destructive portfolio action."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    confirm_label,
                    callback_data=f"{CALLBACK_PREFIX}:confirm:{action_id}",
                ),
                InlineKeyboardButton(
                    cancel_label,
                    callback_data=f"{CALLBACK_PREFIX}:cancel:{action_id}",
                ),
            ]
        ]
    )


def undo_keyboard(action_id: str, *, undo_label: str) -> InlineKeyboardMarkup:
    """Inline keyboard shown after a completed portfolio action."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    undo_label,
                    callback_data=f"{CALLBACK_PREFIX}:undo:{action_id}",
                )
            ]
        ]
    )


def snapshot_strategies(
    repository: DataRepository,
    tickers: list[str],
) -> dict[str, TickerStrategy]:
    """Capture stored strategies for tickers before a portfolio mutation."""
    snapshots: dict[str, TickerStrategy] = {}
    for ticker in tickers:
        symbol = normalize_ticker(ticker)
        strategy = repository.get_ticker_strategy(symbol)
        if strategy is not None:
            snapshots[symbol] = strategy.model_copy(deep=True)
    return snapshots


def save_pending_action(
    repository: DataRepository,
    *,
    action_type: str,
    developer_chat_id: int,
    portfolio_before: Portfolio,
    strategy_snapshots: dict[str, TickerStrategy],
    payload: dict[str, str | float | bool | None],
) -> DeveloperPortfolioAction:
    """Persist a pending confirm action, replacing any previous one."""
    action = DeveloperPortfolioAction(
        action_id=new_action_id(),
        status="pending_confirm",
        action_type=action_type,  # type: ignore[arg-type]
        created_at=datetime.now(tz=UTC),
        developer_chat_id=developer_chat_id,
        portfolio_before=portfolio_before.model_copy(deep=True),
        strategy_snapshots=strategy_snapshots,
        payload=payload,
    )
    repository.set_developer_portfolio_action(action)
    return action


def mark_action_completed(
    repository: DataRepository,
    action: DeveloperPortfolioAction,
    *,
    users_notified: int,
) -> DeveloperPortfolioAction:
    """Mark a pending action as completed and eligible for undo."""
    completed = action.model_copy(
        update={"status": "completed", "users_notified": users_notified}
    )
    repository.set_developer_portfolio_action(completed)
    return completed


def clear_developer_action(repository: DataRepository) -> None:
    """Remove the stored developer portfolio action."""
    repository.set_developer_portfolio_action(None)


def load_action(repository: DataRepository) -> DeveloperPortfolioAction | None:
    """Return the current developer portfolio action, if any."""
    return repository.get_developer_portfolio_action()
