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
