"""External data collectors for markets and news."""

from collectors.base import CollectorContext, CollectorResult
from collectors.market_data import (
    MarketDataBatchResult,
    MarketDataCollector,
    MarketDataService,
    ensure_cached_quote,
    fetch_quote,
    portfolio_tickers,
)
from collectors.news_data import NewsDataCollector, NewsDataService, NewsFetchBatchResult
from collectors.sector_data import SectorDataCollector

__all__ = [
    "CollectorContext",
    "CollectorResult",
    "MarketDataBatchResult",
    "MarketDataCollector",
    "MarketDataService",
    "NewsDataCollector",
    "NewsDataService",
    "NewsFetchBatchResult",
    "SectorDataCollector",
    "ensure_cached_quote",
    "fetch_quote",
    "portfolio_tickers",
]
