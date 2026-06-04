"""Sector and industry-level data collection."""

import logging

from collectors.base import BaseCollector, CollectorContext, CollectorResult

logger = logging.getLogger(__name__)


class SectorDataCollector(BaseCollector):
    """Fetch sector-level indicators for configured focus industries."""

    name = "sector_data"

    def run(self, context: CollectorContext) -> CollectorResult:
        logger.debug(
            "SectorDataCollector pending for %d industries",
            len(context.app_config.focus_industries),
        )
        return CollectorResult(
            name=self.name,
            success=True,
            message="sector collection not implemented",
        )
