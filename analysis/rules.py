"""Deterministic rules for alerts and recommendations."""

from dataclasses import dataclass

from storage.models import AppConfig, BotState, Portfolio


@dataclass(frozen=True)
class RulesEngine:
    """Evaluate portfolio and market changes without LLM inference."""

    app_config: AppConfig

    def evaluate(self, portfolio: Portfolio, state: BotState) -> list[str]:
        """Return advisory messages based on configured thresholds."""
        _ = portfolio
        _ = state
        threshold = self.app_config.alert_price_change_pct
        return [f"rules engine ready (alert threshold {threshold}% )"]
