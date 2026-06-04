"""Compose human-readable summaries from collector output."""

from dataclasses import dataclass

from analysis.llm import LlmAdvisoryResult, LlmClient
from analysis.rules import AlertCandidate, RulesEngine
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
        alerts = self.rules.evaluate(portfolio, state, news_cache)
        lines = [
            "Portfolio intelligence digest",
            f"Positions: {len(portfolio.positions)}",
            f"Cached news: {len(news_cache.items)}",
            f"Pending alerts: {len(state.pending_alerts)}",
            f"Rule alerts: {len(alerts)}",
        ]
        lines.extend(self._format_alert(candidate) for candidate in alerts)

        if self.app_config.enable_llm_summaries:
            advisory = self.llm.synthesize_advisory(
                portfolio,
                self.app_config,
                state,
                news_cache,
                alerts,
            )
            lines.extend(self._format_advisory(advisory))

        return "\n".join(lines)

    def _format_alert(self, candidate: AlertCandidate) -> str:
        target = candidate.ticker or candidate.industry or "portfolio"
        return (
            f"[{candidate.urgency.upper()}] {candidate.title} "
            f"({candidate.type}, {target}): {candidate.explanation}"
        )

    def _format_advisory(self, advisory: LlmAdvisoryResult) -> list[str]:
        lines = [
            f"LLM advisory ({advisory.source}, {advisory.urgency}): {advisory.summary}",
        ]
        if advisory.suggested_actions:
            actions = "; ".join(advisory.suggested_actions)
            lines.append(f"Suggested actions: {actions}")
        if advisory.error:
            lines.append(f"LLM note: {advisory.error}")
        return lines
