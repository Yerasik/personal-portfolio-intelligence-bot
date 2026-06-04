"""External data collectors for markets and news."""

from collectors.base import CollectorContext, CollectorResult
from collectors.market_data import MarketDataCollector
from collectors.news_data import NewsDataCollector
from collectors.sector_data import SectorDataCollector

__all__ = [
    "CollectorContext",
    "CollectorResult",
    "MarketDataCollector",
    "NewsDataCollector",
    "SectorDataCollector",
]
