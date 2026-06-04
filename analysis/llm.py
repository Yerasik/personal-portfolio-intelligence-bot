"""Ollama-backed portfolio advisory summaries."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from analysis.rules import AlertCandidate
from collectors.market_data import portfolio_tickers
from config.settings import RuntimeSettings
from storage.models import AppConfig, BotState, NewsCache, NewsItem, Portfolio

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_BASE_URL = "http://ollama:11434"
DEFAULT_OLLAMA_MODEL = "llama3.1:8b"
DEFAULT_REQUEST_TIMEOUT_SECONDS = 90.0
MAX_NEWS_IN_PROMPT = 6

AdvisoryUrgency = Literal["info", "warning", "urgent"]
AdvisorySource = Literal["ollama", "fallback"]

_URGENCY_RANK = {"info": 0, "warning": 1, "urgent": 2}

_SYSTEM_INSTRUCTIONS = (
    "You are a portfolio advisory assistant. Provide review-only guidance. "
    "Never recommend executing trades, order sizes, or automatic actions. "
    "Use suggested actions such as review, hold, investigate, or monitor."
)


class ParsedAdvisoryResponse(BaseModel):
    """Expected JSON payload returned by the Ollama model."""

    urgency: AdvisoryUrgency = "info"
    summary: str = Field(min_length=1)
    suggested_actions: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class LlmAdvisoryResult:
    """Compact structured advisory output."""

    urgency: AdvisoryUrgency
    summary: str
    suggested_actions: list[str]
    source: AdvisorySource = "fallback"
    error: str | None = None


def resolve_ollama_settings(
    settings: RuntimeSettings,
    app_config: AppConfig | None = None,
) -> tuple[str, str]:
    """Resolve Ollama endpoint settings from environment variables with config fallback."""
    config_base = app_config.ollama_base_url.strip() if app_config else ""
    config_model = app_config.ollama_model.strip() if app_config else ""

    base_url = settings.ollama_base_url or config_base or DEFAULT_OLLAMA_BASE_URL
    model = settings.ollama_model or config_model or DEFAULT_OLLAMA_MODEL
    return base_url.rstrip("/"), model


def _format_holdings(portfolio: Portfolio) -> str:
    if not portfolio.positions:
        return "None"
    lines = []
    for position in portfolio.positions:
        parts = [f"{position.ticker.strip().upper()} ({position.shares:g} shares)"]
        if position.cost_basis is not None:
            parts.append(f"cost basis {position.cost_basis:.2f}")
        lines.append(" ".join(parts))
    return "\n".join(f"- {line}" for line in lines)


def _format_prices(state: BotState, portfolio: Portfolio) -> str:
    symbols = portfolio_tickers(portfolio)
    lines: list[str] = []
    for symbol in symbols:
        quote = state.latest_prices.get(symbol)
        if quote is None or quote.price is None:
            lines.append(f"- {symbol}: price unavailable")
            continue
        change = (
            f"{quote.change_pct:+.2f}%"
            if quote.change_pct is not None
            else "change n/a"
        )
        label = quote.company_name or symbol
        lines.append(f"- {symbol} ({label}): {quote.price:.2f} ({change})")
    return "\n".join(lines) if lines else "- None"


def _news_timestamp(item: NewsItem) -> datetime:
    return item.published_at or item.fetched_at


def select_relevant_news(
    portfolio: Portfolio,
    app_config: AppConfig,
    news_cache: NewsCache,
    *,
    limit: int = MAX_NEWS_IN_PROMPT,
) -> list[NewsItem]:
    """Pick the most relevant recent tagged news for the prompt."""
    tickers = set(portfolio_tickers(portfolio))
    tickers.update(symbol.strip().upper() for symbol in app_config.extra_watchlist if symbol.strip())
    industries = {label.strip() for label in app_config.focus_industries if label.strip()}

    relevant = [
        item
        for item in news_cache.items
        if tickers.intersection(item.ticker_tags) or industries.intersection(item.sector_tags)
    ]
    relevant.sort(key=_news_timestamp, reverse=True)
    return relevant[:limit]


def _format_news(items: list[NewsItem]) -> str:
    if not items:
        return "- None"
    lines: list[str] = []
    for index, item in enumerate(items, start=1):
        tags = ", ".join(item.ticker_tags + item.sector_tags) or "untagged"
        lines.append(f"{index}. [{tags}] {item.title}")
    return "\n".join(f"- {line}" for line in lines)


def _format_alerts(alerts: list[AlertCandidate]) -> str:
    if not alerts:
        return "- None"
    lines = [
        f"[{alert.urgency}] {alert.title}: {alert.explanation}" for alert in alerts
    ]
    return "\n".join(f"- {line}" for line in lines)


def build_advisory_prompt(
    portfolio: Portfolio,
    app_config: AppConfig,
    state: BotState,
    news_cache: NewsCache,
    alerts: list[AlertCandidate],
) -> str:
    """Build a deterministic concise prompt for Ollama."""
    industries = ", ".join(app_config.focus_industries) or "None"
    news_items = select_relevant_news(portfolio, app_config, news_cache)

    return (
        f"{_SYSTEM_INSTRUCTIONS}\n\n"
        "Portfolio context:\n"
        f"Holdings:\n{_format_holdings(portfolio)}\n"
        f"Focus industries: {industries}\n"
        f"Latest prices:\n{_format_prices(state, portfolio)}\n"
        f"Recent tagged news:\n{_format_news(news_items)}\n"
        f"Triggered rule alerts:\n{_format_alerts(alerts)}\n\n"
        "Respond with JSON only using this schema:\n"
        '{"urgency":"info|warning|urgent","summary":"one concise paragraph",'
        '"suggested_actions":["review","hold","investigate","monitor"]}'
    )


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in model response")

    payload = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("Model response JSON must be an object")
    return payload


def parse_advisory_response(text: str) -> ParsedAdvisoryResponse:
    """Parse and validate the model response text."""
    payload = _extract_json_object(text)
    return ParsedAdvisoryResponse.model_validate(payload)


def build_fallback_advisory(
    alerts: list[AlertCandidate],
    portfolio: Portfolio,
    *,
    error: str | None = None,
) -> LlmAdvisoryResult:
    """Return a deterministic advisory when Ollama is unavailable."""
    if alerts:
        urgency = max(alerts, key=lambda alert: _URGENCY_RANK[alert.urgency]).urgency
        summary = "; ".join(alert.title for alert in alerts[:3])
        if len(alerts) > 3:
            summary += f"; plus {len(alerts) - 3} more alert(s)"
    elif portfolio.positions:
        urgency = "info"
        tickers = ", ".join(portfolio_tickers(portfolio))
        summary = f"No rule alerts triggered. Continue monitoring holdings: {tickers}."
    else:
        urgency = "info"
        summary = "No holdings or alerts to summarize."

    suggested_actions = _fallback_actions(alerts, portfolio)
    return LlmAdvisoryResult(
        urgency=urgency,
        summary=summary,
        suggested_actions=suggested_actions,
        source="fallback",
        error=error,
    )


def _fallback_actions(
    alerts: list[AlertCandidate],
    portfolio: Portfolio,
) -> list[str]:
    actions: list[str] = []
    for alert in alerts:
        if alert.type in {"price_drop", "repeated_negative_news"} and alert.ticker:
            actions.append(f"Review {alert.ticker}")
        elif alert.type == "price_rise" and alert.ticker:
            actions.append(f"Monitor {alert.ticker}")
        elif alert.type == "sector_attention" and alert.industry:
            actions.append(f"Investigate {alert.industry} sector news")
    if not actions and portfolio.positions:
        actions.append("Hold and continue monitoring")
    return list(dict.fromkeys(actions))


class LlmClient:
    """Thin wrapper around the local Ollama HTTP API."""

    def __init__(
        self,
        settings: RuntimeSettings,
        app_config: AppConfig | None = None,
        *,
        timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self._base_url, self._model = resolve_ollama_settings(settings, app_config)
        self._timeout = timeout_seconds

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def model(self) -> str:
        return self._model

    @property
    def is_configured(self) -> bool:
        return bool(self._base_url and self._model)

    def generate(self, prompt: str) -> str:
        """Send a prompt to the Ollama generate API and return the response text."""
        url = f"{self._base_url}/api/generate"
        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
        }

        logger.info("Calling Ollama model=%s at %s", self._model, self._base_url)
        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()

        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("Ollama response must be a JSON object")

        text = body.get("response")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Ollama response missing non-empty 'response' text")
        return text.strip()

    def synthesize_advisory(
        self,
        portfolio: Portfolio,
        app_config: AppConfig,
        state: BotState,
        news_cache: NewsCache,
        alerts: list[AlertCandidate],
    ) -> LlmAdvisoryResult:
        """Build a prompt, call Ollama, and return structured advisory output."""
        if not self.is_configured:
            return build_fallback_advisory(
                alerts,
                portfolio,
                error="Ollama is not configured",
            )

        prompt = build_advisory_prompt(
            portfolio,
            app_config,
            state,
            news_cache,
            alerts,
        )

        try:
            raw_response = self.generate(prompt)
            parsed = parse_advisory_response(raw_response)
        except httpx.TimeoutException as exc:
            logger.warning("Ollama request timed out: %s", exc)
            return build_fallback_advisory(
                alerts,
                portfolio,
                error="Ollama request timed out",
            )
        except httpx.HTTPError as exc:
            logger.warning("Ollama connection failed: %s", exc)
            return build_fallback_advisory(
                alerts,
                portfolio,
                error=f"Ollama connection failed: {exc}",
            )
        except (ValueError, ValidationError, json.JSONDecodeError) as exc:
            logger.warning("Invalid Ollama response: %s", exc)
            return build_fallback_advisory(
                alerts,
                portfolio,
                error=f"Invalid Ollama response: {exc}",
            )
        except Exception as exc:
            logger.exception("Unexpected Ollama error")
            return build_fallback_advisory(
                alerts,
                portfolio,
                error=f"Unexpected Ollama error: {exc}",
            )

        actions = [action.strip() for action in parsed.suggested_actions if action.strip()]
        if not actions:
            actions = _fallback_actions(alerts, portfolio)

        return LlmAdvisoryResult(
            urgency=parsed.urgency,
            summary=parsed.summary.strip(),
            suggested_actions=actions,
            source="ollama",
        )
