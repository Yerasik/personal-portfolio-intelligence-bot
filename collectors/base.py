"""Shared types for collector modules."""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from storage.models import AppConfig, Portfolio
from storage.repository import DataRepository


@dataclass(frozen=True)
class CollectorContext:
    """Inputs available to all collectors during a scheduled run."""

    repository: DataRepository
    app_config: AppConfig
    portfolio: Portfolio


@dataclass(frozen=True)
class CollectorResult:
    """Outcome metadata for a collector execution."""

    name: str
    success: bool
    message: str
    finished_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


class BaseCollector:
    """Base class for scheduled data collectors."""

    name: str = "base"

    def run(self, context: CollectorContext) -> CollectorResult:
        """Execute the collector; subclasses override this method."""
        _ = context
        return CollectorResult(
            name=self.name,
            success=True,
            message="not implemented",
        )
