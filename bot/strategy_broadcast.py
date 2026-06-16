"""Broadcast stored ticker strategies to ordinary Telegram users."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from analysis.llm import LlmClient
from analysis.strategy_writer import (
    generate_strategy_announcement,
    localized_strategy_text,
    translate_strategy_text,
)
from bot.i18n import normalize_language
from bot.notifier import TelegramNotifier
from collectors.market_data import portfolio_tickers
from storage.models import AppConfig, BotState, TickerStrategy
from storage.portfolio_ops import normalize_ticker
from storage.repository import DataRepository

logger = logging.getLogger(__name__)

NotifyMode = Literal["summary", "announcement"]


@dataclass(frozen=True)
class StrategyBroadcastResult:
    """Outcome of notifying ordinary users about one ticker strategy."""

    ticker: str
    skipped: bool = False
    skip_reason: str = ""
    users_notified: int = 0
    translations_saved: int = 0


@dataclass(frozen=True)
class StrategyBroadcastReport:
    """Aggregate result across the portfolio."""

    results: list[StrategyBroadcastResult]
    ordinary_user_count: int

    @property
    def notified_total(self) -> int:
        return sum(result.users_notified for result in self.results)

    @property
    def skipped_tickers(self) -> list[str]:
        return [result.ticker for result in self.results if result.skipped]


def _ordinary_languages(repository: DataRepository) -> set[str]:
    users = repository.load_users().users
    languages = {normalize_language(user.language) for user in users if user.role == "ordinary"}
    return languages or {"en"}


def _strategy_text_for_delivery(
    llm: LlmClient,
    strategy: TickerStrategy,
    lang: str,
    *,
    app_config: AppConfig,
) -> str:
    normalized = normalize_language(lang)
    cached = strategy.strategy_text_by_language.get(normalized)
    if cached:
        return cached
    if normalized == "en":
        return strategy.strategy_text
    return localized_strategy_text(
        llm,
        strategy,
        normalized,
        enabled=app_config.enable_llm_summaries,
    )


def ensure_strategy_translations(
    repository: DataRepository,
    llm: LlmClient,
    strategy: TickerStrategy,
    languages: set[str],
    *,
    app_config: AppConfig,
    save: bool,
    dry_run: bool = False,
) -> tuple[TickerStrategy, int]:
    """Fill missing localized strategy text for ordinary user languages."""
    saved = 0
    symbol = strategy.ticker
    for lang in sorted(languages):
        normalized = normalize_language(lang)
        if strategy.strategy_text_by_language.get(normalized):
            continue
        if normalized == "en":
            text = strategy.strategy_text
        elif dry_run:
            text = strategy.strategy_text
        else:
            text = translate_strategy_text(
                llm,
                symbol,
                strategy.strategy_text,
                language=normalized,
                enabled=app_config.enable_llm_summaries,
            )
        if save and not dry_run:
            updated = repository.set_strategy_translation(symbol, normalized, text)
            if updated is not None:
                strategy = updated
        else:
            translations = dict(strategy.strategy_text_by_language)
            translations[normalized] = text
            strategy = strategy.model_copy(
                update={"strategy_text_by_language": translations}
            )
        saved += 1
    return strategy, saved


def notify_ticker_strategy(
    repository: DataRepository,
    notifier: TelegramNotifier,
    llm: LlmClient,
    *,
    symbol: str,
    shares: float,
    app_config: AppConfig,
    state: BotState,
    mode: NotifyMode = "summary",
    save_translations: bool = False,
    dry_run: bool = False,
) -> StrategyBroadcastResult:
    """Send one ticker's strategy to every ordinary user."""
    strategy = repository.get_ticker_strategy(symbol)
    if strategy is None:
        return StrategyBroadcastResult(
            ticker=symbol,
            skipped=True,
            skip_reason="no stored strategy",
        )

    languages = _ordinary_languages(repository)
    strategy, translations_saved = ensure_strategy_translations(
        repository,
        llm,
        strategy,
        languages,
        app_config=app_config,
        save=save_translations,
        dry_run=dry_run,
    )

    ordinary_users = [
        user for user in repository.load_users().users if user.role == "ordinary"
    ]
    if not ordinary_users:
        return StrategyBroadcastResult(
            ticker=symbol,
            skipped=True,
            skip_reason="no ordinary users",
            translations_saved=translations_saved,
        )

    if dry_run:
        logger.info(
            "Dry run: would notify %d ordinary user(s) about %s (%s mode)",
            len(ordinary_users),
            symbol,
            mode,
        )
        return StrategyBroadcastResult(
            ticker=symbol,
            users_notified=len(ordinary_users),
            translations_saved=translations_saved,
        )

    if mode == "announcement":
        quote = state.latest_prices.get(symbol)
        company_name = quote.company_name if quote is not None else ""
        users_notified = notifier.notify_new_ticker_strategy(
            repository,
            symbol,
            shares,
            llm=llm,
            app_config=app_config,
            strategy_text=strategy.strategy_text,
            announcement_en=generate_strategy_announcement(
                llm,
                symbol,
                strategy.strategy_text,
                shares=shares,
                company_name=company_name,
                language="en",
                enabled=app_config.enable_llm_summaries,
            ),
            state=state,
            strategy_text_by_language=strategy.strategy_text_by_language,
        )
        return StrategyBroadcastResult(
            ticker=symbol,
            users_notified=users_notified,
            translations_saved=translations_saved,
        )

    users_notified = notifier.notify_strategy_content(
        repository,
        symbol=symbol,
        text_for_language=lambda lang, record=strategy: _strategy_text_for_delivery(
            llm,
            record,
            lang,
            app_config=app_config,
        ),
    )
    return StrategyBroadcastResult(
        ticker=symbol,
        users_notified=users_notified,
        translations_saved=translations_saved,
    )


def notify_portfolio_strategies(
    repository: DataRepository,
    notifier: TelegramNotifier,
    llm: LlmClient,
    *,
    app_config: AppConfig,
    tickers: list[str] | None = None,
    mode: NotifyMode = "summary",
    save_translations: bool = False,
    dry_run: bool = False,
) -> StrategyBroadcastReport:
    """Broadcast strategies for portfolio tickers to ordinary users."""
    portfolio = repository.load_portfolio()
    state = repository.load_state()
    symbols = [normalize_ticker(symbol) for symbol in (tickers or portfolio_tickers(portfolio))]
    shares_by_ticker = {
        normalize_ticker(position.ticker): position.shares
        for position in portfolio.positions
    }

    ordinary_users = [
        user for user in repository.load_users().users if user.role == "ordinary"
    ]
    results: list[StrategyBroadcastResult] = []
    for symbol in symbols:
        results.append(
            notify_ticker_strategy(
                repository,
                notifier,
                llm,
                symbol=symbol,
                shares=shares_by_ticker.get(symbol, 1.0),
                app_config=app_config,
                state=state,
                mode=mode,
                save_translations=save_translations,
                dry_run=dry_run,
            )
        )

    return StrategyBroadcastReport(
        results=results,
        ordinary_user_count=len(ordinary_users),
    )
