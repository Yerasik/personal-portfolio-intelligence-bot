"""High-level accessors for persisted application data.

All bot modules should load/save JSON through this class rather than calling
JsonStore directly — it keeps path handling consistent.
"""

import logging
from collections.abc import Callable
from typing import Literal

from storage.json_store import JsonStore
from storage.languages import SUPPORTED_LANGUAGES, normalize_language
from storage.models import (
    AppConfig,
    BotState,
    BotUser,
    BotUsers,
    CatalystEventsFile,
    DeveloperPortfolioAction,
    NewsCache,
    PerformanceHistory,
    Portfolio,
    PortfolioPerformanceSnapshot,
    SignalsFile,
    TickerIndustryMap,
    TickerMetadata,
    TickerStrategies,
    TickerStrategy,
    UserRole,
)
from storage.paths import DataPaths
from storage.portfolio_ops import (
    CashDepositResult,
    PortfolioTickerResult,
    SellTickerResult,
    add_ticker_to_portfolio,
    deposit_cash_to_portfolio,
    normalize_ticker,
    portfolio_has_ticker,
    remove_ticker_from_portfolio,
    sell_ticker_from_portfolio,
    validate_ticker_format,
    verify_ticker_exists,
)

logger = logging.getLogger(__name__)


class DataRepository:
    """Typed load/save operations for all JSON-backed documents."""

    def __init__(self, paths: DataPaths, store: JsonStore | None = None) -> None:
        """Bind to a data directory; optionally inject a JsonStore for tests."""
        self._paths = paths
        self._store = store or JsonStore()

    @property
    def paths(self) -> DataPaths:
        """Resolved paths to config.json, portfolio.json, state.json, etc."""
        return self._paths

    def load_config(self) -> AppConfig:
        """Read and validate data/config.json."""
        return self._store.read_model(self._paths.config, AppConfig)

    def save_config(self, config: AppConfig) -> None:
        """Write data/config.json atomically."""
        self._store.write_model(self._paths.config, config)

    def load_portfolio(self) -> Portfolio:
        """Read and validate data/portfolio.json (your holdings)."""
        return self._store.read_model(self._paths.portfolio, Portfolio)

    def save_portfolio(self, portfolio: Portfolio) -> None:
        """Write data/portfolio.json atomically."""
        self._store.write_model(self._paths.portfolio, portfolio)

    def add_ticker_to_portfolio(
        self,
        ticker: str,
        *,
        shares: float = 1.0,
        cost_basis: float | None = None,
        verify_market: bool = True,
    ) -> PortfolioTickerResult:
        """Add a validated ticker to portfolio.json under a single file lock."""
        normalized = normalize_ticker(ticker)
        format_error = validate_ticker_format(normalized)
        if format_error:
            return PortfolioTickerResult(False, format_error, normalized)

        if verify_market:
            current = self.load_portfolio()
            if not portfolio_has_ticker(current, normalized):
                market_error = verify_ticker_exists(normalized)
                if market_error:
                    return PortfolioTickerResult(False, market_error, normalized)

        state = self.load_state()
        result_holder: list[PortfolioTickerResult] = []

        def _mutate(portfolio: Portfolio) -> Portfolio:
            updated, result = add_ticker_to_portfolio(
                portfolio,
                normalized,
                shares=shares,
                cost_basis=cost_basis,
                state=state,
            )
            result_holder.append(result)
            return updated

        self._store.mutate_model(self._paths.portfolio, Portfolio, _mutate)
        result = result_holder[0]
        if result.success and result.is_new_position:
            try:
                from analysis.industries import seed_ticker_industry_if_missing

                seeded = seed_ticker_industry_if_missing(self, normalized)
            except Exception:
                logger.exception("Failed to seed industry mapping for %s", normalized)
                seeded = ""
            else:
                if seeded:
                    result = PortfolioTickerResult(
                        success=result.success,
                        message=result.message,
                        ticker=result.ticker,
                        is_new_position=result.is_new_position,
                        purchase_cost=result.purchase_cost,
                        purchase_currency=result.purchase_currency,
                        cash_balance_hkd=result.cash_balance_hkd,
                        industry_seeded=seeded,
                    )
        return result

    def remove_ticker_from_portfolio(self, ticker: str) -> PortfolioTickerResult:
        """Remove a ticker from portfolio.json under a single file lock."""
        normalized = normalize_ticker(ticker)
        format_error = validate_ticker_format(normalized)
        if format_error:
            return PortfolioTickerResult(False, format_error, normalized)

        result_holder: list[PortfolioTickerResult] = []

        def _mutate(portfolio: Portfolio) -> Portfolio:
            updated, result = remove_ticker_from_portfolio(portfolio, normalized)
            result_holder.append(result)
            return updated

        self._store.mutate_model(self._paths.portfolio, Portfolio, _mutate)
        return result_holder[0]

    def deposit_cash_to_portfolio(
        self,
        amount: float,
        *,
        currency: str = "HKD",
    ) -> CashDepositResult:
        """Credit cash to portfolio.json under a single file lock."""
        result_holder: list[CashDepositResult] = []

        def _mutate(portfolio: Portfolio) -> Portfolio:
            updated, result = deposit_cash_to_portfolio(
                portfolio,
                amount,
                currency=currency,
            )
            result_holder.append(result)
            return updated

        self._store.mutate_model(self._paths.portfolio, Portfolio, _mutate)
        return result_holder[0]

    def sell_ticker_from_portfolio(
        self,
        ticker: str,
        *,
        sell_price: float,
        shares: float | None = None,
    ) -> SellTickerResult:
        """Sell shares at a price, credit cash, and update portfolio.json."""
        normalized = normalize_ticker(ticker)
        format_error = validate_ticker_format(normalized)
        if format_error:
            return SellTickerResult(False, format_error, normalized)

        state = self.load_state()
        result_holder: list[SellTickerResult] = []

        def _mutate(portfolio: Portfolio) -> Portfolio:
            updated, result = sell_ticker_from_portfolio(
                portfolio,
                normalized,
                sell_price=sell_price,
                shares=shares,
                state=state,
            )
            result_holder.append(result)
            return updated

        self._store.mutate_model(self._paths.portfolio, Portfolio, _mutate)
        return result_holder[0]

    def load_state(self) -> BotState:
        """Read runtime state: latest prices, alerts, last fetch timestamps."""
        return self._store.read_model(self._paths.state, BotState)

    def save_state(self, state: BotState) -> None:
        """Write data/state.json atomically."""
        self._store.write_model(self._paths.state, state)

    def get_developer_portfolio_action(self) -> DeveloperPortfolioAction | None:
        """Return the pending or undoable developer portfolio action."""
        return self.load_state().developer_portfolio_action

    def set_developer_portfolio_action(
        self,
        action: DeveloperPortfolioAction | None,
    ) -> None:
        """Store or clear the developer portfolio confirm/undo action."""

        def _mutate(state: BotState) -> BotState:
            return state.model_copy(update={"developer_portfolio_action": action})

        self._store.mutate_model(self._paths.state, BotState, _mutate)

    def load_news_cache(self) -> NewsCache:
        """Read cached RSS articles from data/news_cache.json."""
        return self._store.read_model(self._paths.news_cache, NewsCache)

    def save_news_cache(self, cache: NewsCache) -> None:
        """Write data/news_cache.json atomically."""
        self._store.write_model(self._paths.news_cache, cache)

    def load_catalyst_events(self) -> CatalystEventsFile:
        """Read cached catalyst calendar from data/catalyst_events.json."""
        return self._store.read_model(self._paths.catalyst_events, CatalystEventsFile)

    def save_catalyst_events(self, events: CatalystEventsFile) -> None:
        """Write data/catalyst_events.json atomically."""
        self._store.write_model(self._paths.catalyst_events, events)

    def load_signals(self) -> SignalsFile:
        """Read derived signals from data/signals.json."""
        return self._store.read_model(self._paths.signals, SignalsFile)

    def save_signals(self, signals: SignalsFile) -> None:
        """Write data/signals.json atomically."""
        self._store.write_model(self._paths.signals, signals)

    def load_performance_history(self) -> PerformanceHistory:
        """Read append-only portfolio snapshots from performance_history.json."""
        return self._store.read_model(self._paths.performance_history, PerformanceHistory)

    def save_performance_history(self, history: PerformanceHistory) -> None:
        """Write performance_history.json atomically."""
        self._store.write_model(self._paths.performance_history, history)

    def append_performance_snapshot(
        self,
        snapshot: PortfolioPerformanceSnapshot,
    ) -> PerformanceHistory:
        """Append one snapshot under a single file lock."""
        def _mutate(history: PerformanceHistory) -> PerformanceHistory:
            return history.model_copy(
                update={"snapshots": [*history.snapshots, snapshot]}
            )

        return self._store.mutate_model(
            self._paths.performance_history,
            PerformanceHistory,
            _mutate,
        )

    def load_ticker_industries(self) -> TickerIndustryMap:
        """Read static ticker-to-industry mappings from data/ticker_industries.json."""
        return self._store.read_model(self._paths.ticker_industries, TickerIndustryMap)

    def save_ticker_industries(self, mapping: TickerIndustryMap) -> None:
        """Write data/ticker_industries.json atomically."""
        self._store.write_model(self._paths.ticker_industries, mapping)

    def mutate_ticker_industries(
        self,
        mutator: Callable[[TickerIndustryMap], TickerIndustryMap],
    ) -> TickerIndustryMap:
        """Read-modify-write ticker_industries.json under a file lock."""
        return self._store.mutate_model(
            self._paths.ticker_industries,
            TickerIndustryMap,
            mutator,
        )

    def load_ticker_metadata(self) -> TickerMetadata:
        """Read cached company names from data/ticker_metadata.json."""
        return self._store.read_model(self._paths.ticker_metadata, TickerMetadata)

    def save_ticker_metadata(self, metadata: TickerMetadata) -> None:
        """Write data/ticker_metadata.json atomically."""
        self._store.write_model(self._paths.ticker_metadata, metadata)

    def load_ticker_strategies(self) -> TickerStrategies:
        """Read per-ticker investment ideas from data/ticker_strategies.json."""
        return self._store.read_model(self._paths.ticker_strategies, TickerStrategies)

    def save_ticker_strategies(self, strategies: TickerStrategies) -> None:
        """Write data/ticker_strategies.json atomically."""
        self._store.write_model(self._paths.ticker_strategies, strategies)

    def get_ticker_strategy(self, ticker: str) -> TickerStrategy | None:
        """Return the stored strategy for a ticker, if any."""
        symbol = normalize_ticker(ticker)
        return self.load_ticker_strategies().by_ticker.get(symbol)

    def upsert_ticker_strategy(
        self,
        ticker: str,
        *,
        developer_reasoning: str,
        strategy_text: str,
        shares_at_add: float | None = None,
        holding_horizon: Literal["long", "short"] | None = None,
        strategy_text_by_language: dict[str, str] | None = None,
    ) -> TickerStrategy:
        """Create or replace the strategy record for a ticker."""
        from datetime import UTC, datetime

        symbol = normalize_ticker(ticker)
        now = datetime.now(tz=UTC)
        strategies = self.load_ticker_strategies()
        existing = strategies.by_ticker.get(symbol)
        translations = dict(strategy_text_by_language or {})
        if "en" not in translations:
            translations["en"] = strategy_text.strip()
        horizon = holding_horizon
        if horizon is None:
            horizon = existing.holding_horizon if existing is not None else "long"
        record = TickerStrategy(
            ticker=symbol,
            developer_reasoning=developer_reasoning.strip(),
            strategy_text=strategy_text.strip(),
            strategy_text_by_language=translations,
            shares_at_add=shares_at_add,
            holding_horizon=horizon,
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
        )
        strategies.by_ticker[symbol] = record
        self.save_ticker_strategies(strategies)
        return record

    def set_strategy_translation(
        self,
        ticker: str,
        language: str,
        text: str,
    ) -> TickerStrategy | None:
        """Cache localized strategy display text for one language."""
        from datetime import UTC, datetime

        from storage.languages import normalize_language

        symbol = normalize_ticker(ticker)
        lang = normalize_language(language)
        cleaned = text.strip()
        if not cleaned:
            return None

        strategies = self.load_ticker_strategies()
        existing = strategies.by_ticker.get(symbol)
        if existing is None:
            return None

        translations = dict(existing.strategy_text_by_language)
        translations[lang] = cleaned
        updated = existing.model_copy(
            update={
                "strategy_text_by_language": translations,
                "updated_at": datetime.now(tz=UTC),
            }
        )
        strategies.by_ticker[symbol] = updated
        self.save_ticker_strategies(strategies)
        return updated

    def edit_ticker_strategy_text(
        self,
        ticker: str,
        strategy_text: str,
        *,
        editor_language: str = "en",
    ) -> tuple[bool, str]:
        """Hard-overwrite the user-facing strategy text for a ticker."""
        from datetime import UTC, datetime

        from storage.languages import normalize_language

        symbol = normalize_ticker(ticker)
        cleaned = strategy_text.strip()
        if not cleaned:
            return False, "empty_text"

        strategies = self.load_ticker_strategies()
        existing = strategies.by_ticker.get(symbol)
        if existing is None:
            return False, "not_found"

        editor_lang = normalize_language(editor_language)
        strategies.by_ticker[symbol] = existing.model_copy(
            update={
                "strategy_text": cleaned,
                "strategy_text_by_language": {editor_lang: cleaned},
                "updated_at": datetime.now(tz=UTC),
            }
        )
        self.save_ticker_strategies(strategies)
        return True, "updated"

    def remove_ticker_strategy(self, ticker: str) -> None:
        """Delete the strategy record when a holding is removed."""
        symbol = normalize_ticker(ticker)
        strategies = self.load_ticker_strategies()
        if symbol not in strategies.by_ticker:
            return
        strategies.by_ticker.pop(symbol, None)
        self.save_ticker_strategies(strategies)

    def load_users(self) -> BotUsers:
        """Read authorized Telegram users from data/users.json."""
        return self._store.read_model(self._paths.users, BotUsers)

    def save_users(self, users: BotUsers) -> None:
        """Write data/users.json atomically."""
        self._store.write_model(self._paths.users, users)

    def find_user(self, chat_id: int) -> BotUser | None:
        """Return the authorized user record for a chat id, if any."""
        for user in self.load_users().users:
            if user.chat_id == chat_id:
                return user
        return None

    def is_authorized_user(self, chat_id: int) -> bool:
        """Return True when chat_id appears in the users access list."""
        return self.find_user(chat_id) is not None

    def user_language(self, chat_id: int) -> str:
        """Return the stored language for a user, defaulting to English."""
        user = self.find_user(chat_id)
        return user.language if user is not None else "en"

    def is_developer(self, chat_id: int) -> bool:
        """Return True when the user has the developer role."""
        user = self.find_user(chat_id)
        return user is not None and user.role == "developer"

    def bootstrap_users_if_empty(self, seed_chat_id: int) -> BotUsers:
        """Create a single developer user when users.json has no entries."""
        users = self.load_users()
        if users.users:
            return users
        bootstrapped = BotUsers(
            users=[
                BotUser(
                    chat_id=seed_chat_id,
                    language="en",
                    role="developer",
                )
            ]
        )
        self.save_users(bootstrapped)
        return bootstrapped

    def set_user_language(self, chat_id: int, language: str) -> tuple[bool, str]:
        """Update a user's language preference under file lock."""
        lang = normalize_language(language)
        if lang not in SUPPORTED_LANGUAGES:
            return False, "invalid_language"

        updated = False

        def _mutate(users: BotUsers) -> BotUsers:
            nonlocal updated
            for index, user in enumerate(users.users):
                if user.chat_id != chat_id:
                    continue
                users.users[index] = user.model_copy(update={"language": lang})
                updated = True
                break
            return users

        self._store.mutate_model(self._paths.users, BotUsers, _mutate)
        if not updated:
            return False, "not_found"
        return True, lang

    def add_user(
        self,
        chat_id: int,
        *,
        role: UserRole = "ordinary",
        language: str = "en",
    ) -> tuple[bool, str]:
        """Add an authorized user under file lock."""
        lang = normalize_language(language)
        if lang not in SUPPORTED_LANGUAGES:
            return False, "invalid_language"

        added = False

        def _mutate(users: BotUsers) -> BotUsers:
            nonlocal added
            for user in users.users:
                if user.chat_id == chat_id:
                    return users
            users.users.append(
                BotUser(chat_id=chat_id, language=lang, role=role)
            )
            added = True
            return users

        self._store.mutate_model(self._paths.users, BotUsers, _mutate)
        if not added:
            return False, "exists"
        return True, "added"

    def remove_user(self, chat_id: int) -> tuple[bool, str]:
        """Remove an authorized user under file lock."""
        removed = False

        def _mutate(users: BotUsers) -> BotUsers:
            nonlocal removed
            before = len(users.users)
            users.users = [user for user in users.users if user.chat_id != chat_id]
            removed = len(users.users) < before
            return users

        self._store.mutate_model(self._paths.users, BotUsers, _mutate)
        if not removed:
            return False, "not_found"
        return True, "removed"


def load_config(paths: DataPaths, store: JsonStore | None = None) -> AppConfig:
    """Load and validate config.json."""
    return DataRepository(paths, store).load_config()


def load_portfolio(paths: DataPaths, store: JsonStore | None = None) -> Portfolio:
    """Load and validate portfolio.json."""
    return DataRepository(paths, store).load_portfolio()


def load_state(paths: DataPaths, store: JsonStore | None = None) -> BotState:
    """Load and validate state.json."""
    return DataRepository(paths, store).load_state()


def load_news_cache(paths: DataPaths, store: JsonStore | None = None) -> NewsCache:
    """Load and validate news_cache.json."""
    return DataRepository(paths, store).load_news_cache()


def save_state(
    paths: DataPaths, state: BotState, store: JsonStore | None = None
) -> None:
    """Persist state.json."""
    DataRepository(paths, store).save_state(state)


def save_news_cache(
    paths: DataPaths, cache: NewsCache, store: JsonStore | None = None
) -> None:
    """Persist news_cache.json."""
    DataRepository(paths, store).save_news_cache(cache)


def save_portfolio(
    paths: DataPaths, portfolio: Portfolio, store: JsonStore | None = None
) -> None:
    """Persist portfolio.json."""
    DataRepository(paths, store).save_portfolio(portfolio)
