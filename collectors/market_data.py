"""Market price and quote collection."""

import logging

from collectors.base import BaseCollector, CollectorContext, CollectorResult

logger = logging.getLogger(__name__)


class MarketDataCollector(BaseCollector):
    """Fetch quotes for portfolio and watchlist tickers."""

    name = "market_data"

    def run(self, context: CollectorContext) -> CollectorResult:
        logger.debug(
            "MarketDataCollector pending for %d positions",
            len(context.portfolio.positions),
        )
        return CollectorResult(
            name=self.name,
            success=True,
            message="market collection not implemented",
        )
