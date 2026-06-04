"""Load environment settings and JSON-backed application configuration."""

from dataclasses import dataclass

from config.settings import RuntimeSettings
from storage.models import AppConfig, BotState, NewsCache, Portfolio
from storage.paths import DataPaths, resolve_data_paths
from storage.repository import DataRepository


@dataclass(frozen=True)
class ConfigurationBundle:
    """Fully resolved settings and persisted documents for startup."""

    runtime: RuntimeSettings
    paths: DataPaths
    app_config: AppConfig
    portfolio: Portfolio
    state: BotState
    news_cache: NewsCache


def load_configuration() -> ConfigurationBundle:
    """Load runtime env settings and hydrate JSON documents from disk."""
    runtime = RuntimeSettings()
    paths = resolve_data_paths(runtime.data_dir)
    repository = DataRepository(paths)

    return ConfigurationBundle(
        runtime=runtime,
        paths=paths,
        app_config=repository.load_config(),
        portfolio=repository.load_portfolio(),
        state=repository.load_state(),
        news_cache=repository.load_news_cache(),
    )
