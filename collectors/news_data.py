"""News feed collection and cache updates."""

import logging

from collectors.base import BaseCollector, CollectorContext, CollectorResult

logger = logging.getLogger(__name__)


class NewsDataCollector(BaseCollector):
    """Fetch news for holdings and focus industries."""

    name = "news_data"

    def run(self, context: CollectorContext) -> CollectorResult:
        logger.debug(
            "NewsDataCollector pending for %d watchlist entries",
            len(context.app_config.extra_watchlist),
        )
        return CollectorResult(
            name=self.name,
            success=True,
            message="news collection not implemented",
        )
