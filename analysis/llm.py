"""Portfolio advisory summaries via HKU GenAI APIs with Ollama fallback.

When enable_llm_summaries is true, builds a prompt from portfolio + news + alerts,
tries HKU Claude Sonnet first, then GPT-5.5, then local Ollama. On any
failure, falls back to deterministic text built from rule alerts.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from analysis.hku_backends import call_hku_claude_converse, call_hku_openai_chat
from analysis.industries import build_news_focus_industries
from analysis.rules import AlertCandidate
from collectors.market_data import portfolio_tickers
from config.hku_api import resolve_hku_api_settings
from config.ollama import resolve_ollama_settings
from config.settings import RuntimeSettings
from storage.models import AppConfig, BotState, NewsCache, NewsItem, Portfolio

logger = logging.getLogger(__name__)

# CPU-only inference of large/"thinking" models (e.g. qwen3:30b) can take
# several minutes per request, so allow a generous ceiling before timing out.
DEFAULT_REQUEST_TIMEOUT_SECONDS = 300.0
MAX_NEWS_IN_PROMPT = 6

AdvisoryUrgency = Literal["info", "warning", "urgent"]
AdvisorySource = Literal["hku_claude", "hku_openai", "ollama", "fallback"]

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


def _format_holdings(portfolio: Portfolio) -> str:
    """Format portfolio positions as bullet lines for the LLM prompt."""
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
    """Format latest cached quotes from state.json for the LLM prompt."""
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
    """Prefer article publish time; fall back to when we fetched it."""
    return item.published_at or item.fetched_at


def select_relevant_news(
    portfolio: Portfolio,
    app_config: AppConfig,
    news_cache: NewsCache,
    *,
    ticker_to_industry: dict[str, str] | None = None,
    limit: int = MAX_NEWS_IN_PROMPT,
) -> list[NewsItem]:
    """Pick the most relevant recent tagged news for the prompt."""
    tickers = set(portfolio_tickers(portfolio))
    tickers.update(symbol.strip().upper() for symbol in app_config.extra_watchlist if symbol.strip())
    industries = set(
        build_news_focus_industries(
            app_config.focus_industries,
            portfolio,
            ticker_to_industry or {},
        )
    )

    relevant = [
        item
        for item in news_cache.items
        if tickers.intersection(item.ticker_tags) or industries.intersection(item.sector_tags)
    ]
    relevant.sort(key=_news_timestamp, reverse=True)
    return relevant[:limit]


def _format_news(items: list[NewsItem]) -> str:
    """Format tagged news headlines for the LLM prompt."""
    if not items:
        return "- None"
    lines: list[str] = []
    for index, item in enumerate(items, start=1):
        tags = ", ".join(item.ticker_tags + item.sector_tags) or "untagged"
        lines.append(f"{index}. [{tags}] {item.title}")
    return "\n".join(f"- {line}" for line in lines)


def _format_alerts(alerts: list[AlertCandidate]) -> str:
    """Format rule-engine alerts for the LLM prompt."""
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
    *,
    ticker_to_industry: dict[str, str] | None = None,
    language: str = "en",
) -> str:
    """Build a deterministic concise prompt for Ollama."""
    from bot.i18n import llm_language_clause

    focus_industries = build_news_focus_industries(
        app_config.focus_industries,
        portfolio,
        ticker_to_industry or {},
    )
    industries = ", ".join(focus_industries) or "None"
    news_items = select_relevant_news(
        portfolio,
        app_config,
        news_cache,
        ticker_to_industry=ticker_to_industry,
    )

    return (
        f"{_SYSTEM_INSTRUCTIONS}\n\n"
        "Portfolio context:\n"
        f"Holdings:\n{_format_holdings(portfolio)}\n"
        f"Focus industries: {industries}\n"
        f"Latest prices:\n{_format_prices(state, portfolio)}\n"
        f"Recent tagged news:\n{_format_news(news_items)}\n"
        f"Triggered rule alerts:\n{_format_alerts(alerts)}\n\n"
        f"{llm_language_clause(language)}\n\n"
        "Respond with JSON only using this schema:\n"
        '{"urgency":"info|warning|urgent","summary":"one concise paragraph",'
        '"suggested_actions":["review","hold","investigate","monitor"]}'
    )


def _extract_json_object(text: str) -> dict[str, Any]:
    """Pull the first JSON object from model output (strips markdown fences)."""
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
    """Return a deterministic advisory when all LLM backends are unavailable."""
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
    """Map alert types to review-only suggested actions when LLM is unavailable."""
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


class LlmGenerationError(RuntimeError):
    """Raised when every configured LLM backend fails."""


class LlmClient:
    """LLM client with Sonnet → GPT → Ollama fallback."""

    def __init__(
        self,
        settings: RuntimeSettings,
        app_config: AppConfig | None = None,
        *,
        timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        """Resolve HKU and Ollama settings and store HTTP timeout."""
        (
            self._hku_base_url,
            self._hku_api_key,
            self._hku_claude_models,
            self._hku_openai_models,
            self._hku_openai_api_version,
        ) = resolve_hku_api_settings(settings)
        self._ollama_base_url, self._ollama_model = resolve_ollama_settings(
            settings,
            app_config,
        )
        self._timeout = timeout_seconds
        self._last_source: AdvisorySource | None = None

    @property
    def base_url(self) -> str:
        return self._ollama_base_url

    @property
    def model(self) -> str:
        return self._ollama_model

    @property
    def last_source(self) -> AdvisorySource | None:
        return self._last_source

    @property
    def is_configured(self) -> bool:
        return bool(self._hku_api_key) or bool(
            self._ollama_base_url and self._ollama_model
        )

    def generate(self, prompt: str) -> str:
        """Generate text using HKU APIs first, then Ollama."""
        text, source = self._generate_with_fallback(prompt)
        self._last_source = source
        return text

    def _generate_with_fallback(self, prompt: str) -> tuple[str, AdvisorySource]:
        """Try Claude Sonnet, GPT, then Ollama."""
        errors: list[str] = []

        if self._hku_api_key:
            for claude_model in self._hku_claude_models:
                try:
                    with httpx.Client(timeout=self._timeout) as client:
                        text = call_hku_claude_converse(
                            client=client,
                            base_url=self._hku_base_url,
                            api_key=self._hku_api_key,
                            model=claude_model,
                            prompt=prompt,
                        )
                    return text, "hku_claude"
                except Exception as exc:
                    message = f"HKU Claude ({claude_model}): {exc}"
                    logger.warning(message)
                    errors.append(message)

            for openai_model in self._hku_openai_models:
                try:
                    with httpx.Client(timeout=self._timeout) as client:
                        text = call_hku_openai_chat(
                            client=client,
                            base_url=self._hku_base_url,
                            api_key=self._hku_api_key,
                            model=openai_model,
                            api_version=self._hku_openai_api_version,
                            prompt=prompt,
                        )
                    return text, "hku_openai"
                except Exception as exc:
                    message = f"HKU OpenAI ({openai_model}): {exc}"
                    logger.warning(message)
                    errors.append(message)

        if self._ollama_base_url and self._ollama_model:
            try:
                text = self._generate_ollama(prompt)
                return text, "ollama"
            except Exception as exc:
                message = f"Ollama ({self._ollama_model}): {exc}"
                logger.warning(message)
                errors.append(message)

        raise LlmGenerationError("; ".join(errors) if errors else "No LLM backend configured")

    def _generate_ollama(self, prompt: str) -> str:
        """Send a prompt to the Ollama generate API and return the response text."""
        url = f"{self._ollama_base_url}/api/generate"
        payload = {
            "model": self._ollama_model,
            "prompt": prompt,
            "stream": False,
        }

        logger.info(
            "Calling Ollama model=%s at %s",
            self._ollama_model,
            self._ollama_base_url,
        )
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
        *,
        ticker_to_industry: dict[str, str] | None = None,
        language: str = "en",
    ) -> LlmAdvisoryResult:
        """Build a prompt, call the LLM chain, and return structured advisory output."""
        if not self.is_configured:
            return build_fallback_advisory(
                alerts,
                portfolio,
                error="No LLM backend is configured",
            )

        prompt = build_advisory_prompt(
            portfolio,
            app_config,
            state,
            news_cache,
            alerts,
            ticker_to_industry=ticker_to_industry,
            language=language,
        )

        try:
            raw_response, source = self._generate_with_fallback(prompt)
            self._last_source = source
            parsed = parse_advisory_response(raw_response)
        except httpx.TimeoutException as exc:
            logger.warning("LLM request timed out: %s", exc)
            return build_fallback_advisory(
                alerts,
                portfolio,
                error="LLM request timed out",
            )
        except httpx.HTTPError as exc:
            logger.warning("LLM connection failed: %s", exc)
            return build_fallback_advisory(
                alerts,
                portfolio,
                error=f"LLM connection failed: {exc}",
            )
        except LlmGenerationError as exc:
            logger.warning("All LLM backends failed: %s", exc)
            return build_fallback_advisory(
                alerts,
                portfolio,
                error=str(exc),
            )
        except (ValueError, ValidationError, json.JSONDecodeError) as exc:
            logger.warning("Invalid LLM response: %s", exc)
            return build_fallback_advisory(
                alerts,
                portfolio,
                error=f"Invalid LLM response: {exc}",
            )
        except Exception as exc:
            logger.exception("Unexpected LLM error")
            return build_fallback_advisory(
                alerts,
                portfolio,
                error=f"Unexpected LLM error: {exc}",
            )

        actions = [action.strip() for action in parsed.suggested_actions if action.strip()]
        if not actions:
            actions = _fallback_actions(alerts, portfolio)

        return LlmAdvisoryResult(
            urgency=parsed.urgency,
            summary=parsed.summary.strip(),
            suggested_actions=actions,
            source=self._last_source or "fallback",
        )
