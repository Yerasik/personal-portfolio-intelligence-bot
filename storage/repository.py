"""High-level accessors for persisted application data.

All bot modules should load/save JSON through this class rather than calling
JsonStore directly — it keeps path handling consistent.
"""

from storage.json_store import JsonStore
from storage.models import AppConfig, BotState, NewsCache, Portfolio, TickerIndustryMap
from storage.paths import DataPaths


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

    def load_state(self) -> BotState:
        """Read runtime state: latest prices, alerts, last fetch timestamps."""
        return self._store.read_model(self._paths.state, BotState)

    def save_state(self, state: BotState) -> None:
        """Write data/state.json atomically."""
        self._store.write_model(self._paths.state, state)

    def load_news_cache(self) -> NewsCache:
        """Read cached RSS articles from data/news_cache.json."""
        return self._store.read_model(self._paths.news_cache, NewsCache)

    def save_news_cache(self, cache: NewsCache) -> None:
        """Write data/news_cache.json atomically."""
        self._store.write_model(self._paths.news_cache, cache)

    def load_ticker_industries(self) -> TickerIndustryMap:
        """Read static ticker-to-industry mappings from data/ticker_industries.json."""
        return self._store.read_model(self._paths.ticker_industries, TickerIndustryMap)

    def save_ticker_industries(self, mapping: TickerIndustryMap) -> None:
        """Write data/ticker_industries.json atomically."""
        self._store.write_model(self._paths.ticker_industries, mapping)


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
