"""JSON-backed persistence for portfolio data and runtime state."""

from storage.json_store import JsonStorageError, JsonStore
from storage.locking import lock_path_for, locked_json_file
from storage.models import (
    AppConfig,
    BotState,
    MarketQuote,
    NewsCache,
    NewsItem,
    PendingAlert,
    Portfolio,
    Position,
    TickerIndustryMap,
)
from storage.paths import DataPaths, resolve_data_paths
from storage.repository import (
    DataRepository,
    load_config,
    load_news_cache,
    load_portfolio,
    load_state,
    save_news_cache,
    save_portfolio,
    save_state,
)

__all__ = [
    "AppConfig",
    "BotState",
    "MarketQuote",
    "DataPaths",
    "DataRepository",
    "JsonStorageError",
    "JsonStore",
    "NewsCache",
    "NewsItem",
    "PendingAlert",
    "Portfolio",
    "Position",
    "TickerIndustryMap",
    "load_config",
    "load_news_cache",
    "load_portfolio",
    "load_state",
    "lock_path_for",
    "locked_json_file",
    "resolve_data_paths",
    "save_news_cache",
    "save_portfolio",
    "save_state",
]
