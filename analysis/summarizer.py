"""Compose human-readable summaries from collector output."""

from dataclasses import dataclass

from analysis.llm import LlmClient
from analysis.rules import RulesEngine
from storage.models import AppConfig, BotState, NewsCache, Portfolio


@dataclass(frozen=True)
class Summarizer:
    """Combine rules output and optional LLM summaries."""

    app_config: AppConfig
    rules: RulesEngine
    llm: LlmClient

    def build_digest(
        self,
        portfolio: Portfolio,
        state: BotState,
        news_cache: NewsCache,
    ) -> str:
        """Produce a digest message for scheduled Telegram delivery."""
        rule_messages = self.rules.evaluate(portfolio, state)
        lines = [
            "Portfolio intelligence digest (skeleton)",
            f"Positions: {len(portfolio.positions)}",
            f"Cached news: {len(news_cache.items)}",
            f"Pending alerts: {len(state.pending_alerts)}",
            *rule_messages,
        ]
        if self.app_config.enable_llm_summaries and self.llm.is_configured:
            lines.append("LLM summaries enabled (not yet implemented)")
        return "\n".join(lines)
