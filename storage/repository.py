"""High-level accessors for persisted application data."""

from storage.json_store import JsonStore
from storage.models import AppConfig, BotState, NewsCache, Portfolio
from storage.paths import DataPaths


class DataRepository:
    """Typed load/save operations for all JSON-backed documents."""

    def __init__(self, paths: DataPaths, store: JsonStore | None = None) -> None:
        self._paths = paths
        self._store = store or JsonStore()

    @property
    def paths(self) -> DataPaths:
        return self._paths

    def load_config(self) -> AppConfig:
        return self._store.read_model(self._paths.config, AppConfig)

    def save_config(self, config: AppConfig) -> None:
        self._store.write_model(self._paths.config, config)

    def load_portfolio(self) -> Portfolio:
        return self._store.read_model(self._paths.portfolio, Portfolio)

    def save_portfolio(self, portfolio: Portfolio) -> None:
        self._store.write_model(self._paths.portfolio, portfolio)

    def load_state(self) -> BotState:
        return self._store.read_model(self._paths.state, BotState)

    def save_state(self, state: BotState) -> None:
        self._store.write_model(self._paths.state, state)

    def load_news_cache(self) -> NewsCache:
        return self._store.read_model(self._paths.news_cache, NewsCache)

    def save_news_cache(self, cache: NewsCache) -> None:
        self._store.write_model(self._paths.news_cache, cache)


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
