"""External data collectors for markets and news."""

from collectors.base import CollectorContext, CollectorResult
from collectors.market_data import (
    MarketDataBatchResult,
    MarketDataCollector,
    MarketDataService,
    fetch_quote,
    portfolio_tickers,
)
from collectors.news_data import NewsDataCollector
from collectors.sector_data import SectorDataCollector

__all__ = [
    "CollectorContext",
    "CollectorResult",
    "MarketDataBatchResult",
    "MarketDataCollector",
    "MarketDataService",
    "NewsDataCollector",
    "SectorDataCollector",
    "fetch_quote",
    "portfolio_tickers",
]
