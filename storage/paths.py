"""Canonical paths for JSON data files under /app/data."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DataPaths:
    """Resolved filesystem locations for persisted JSON documents."""

    root: Path

    @property
    def config(self) -> Path:
        return self.root / "config.json"

    @property
    def portfolio(self) -> Path:
        return self.root / "portfolio.json"

    @property
    def state(self) -> Path:
        return self.root / "state.json"

    @property
    def news_cache(self) -> Path:
        return self.root / "news_cache.json"

    @property
    def ticker_industries(self) -> Path:
        return self.root / "ticker_industries.json"

    @property
    def ticker_metadata(self) -> Path:
        return self.root / "ticker_metadata.json"

    @property
    def ticker_strategies(self) -> Path:
        return self.root / "ticker_strategies.json"

    @property
    def users(self) -> Path:
        return self.root / "users.json"

    @property
    def signals(self) -> Path:
        return self.root / "signals.json"


def resolve_data_paths(data_dir: str | Path) -> DataPaths:
    """Build path helpers for the configured data directory."""
    root = Path(data_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return DataPaths(root=root)
