"""Best-effort LLM explanations for significant price moves.

Shared by the alert pipeline (run_rule_evaluation_job) and the user-facing
/analyze command so both surfaces produce identical, disclaimer-tagged
explanations. The explanation is hypothetical and never investment advice.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from storage.models import NewsCache, NewsItem

if TYPE_CHECKING:
    from analysis.llm import LlmClient

logger = logging.getLogger(__name__)

MAX_NEWS_IN_PROMPT = 6
_SUMMARY_CLIP = 160

Sentiment = Literal["positive", "negative", "mixed", "uncertain"]
ExplanationSource = Literal["llm", "fallback"]

DISCLAIMER = (
    "This is a hypothetical, best-effort explanation based only on the provided "
    "price and news context. It may be incomplete or inaccurate and is not "
    "investment advice."
)

_FALLBACK_REASON = "No explanation available; only raw price information is shown."

_ROLE_INSTRUCTIONS = (
    "You are a cautious financial analyst. Explain plausible reasons for a "
    "recent stock price move using ONLY the provided price and news context. "
    "Clearly separate speculation from facts, never recommend trades, and "
    "acknowledge uncertainty."
)


@dataclass(frozen=True)
class PriceMoveExplanation:
    """Structured explanation of a single price move."""

    ticker: str
    direction: str
    magnitude: float
    window: str
    drivers: list[str] = field(default_factory=list)
    sentiment: Sentiment = "uncertain"
    assessment: str = ""
    disclaimer: str = DISCLAIMER
    source: ExplanationSource = "fallback"
    error: str | None = None

    def to_message(self, lang: str = "en") -> str:
        """Telegram-ready block labelled as an LLM explanation with disclaimer."""
        from bot.i18n import t

        return (
            f"{t('move_explanation_header', lang)}\n"
            f"{self.reason_text(lang)}\n"
            f"{t('move_explanation_note', lang, disclaimer=self.disclaimer_for(lang))}"
        )

    def disclaimer_for(self, lang: str) -> str:
        from bot.i18n import t

        return t("move_explanation_disclaimer", lang)

    def reason_text(self, lang: str = "en") -> str:
        """Human-readable drivers + sentiment block (without the label/header)."""
        from bot.i18n import t

        lines: list[str] = []
        if self.drivers:
            lines.extend(f"- {driver}" for driver in self.drivers)
        else:
            lines.append(f"- {t('move_explanation_fallback', lang)}")
        assessment = self.assessment or t("move_explanation_uncertain_assessment", lang)
        lines.append(
            t(
                "move_explanation_sentiment",
                lang,
                sentiment=self.sentiment,
                assessment=assessment,
            )
        )
        return "\n".join(lines)


def direction_for_change(pct_change: float) -> str:
    """Map a signed percentage change to an "up"/"down" direction label."""
    return "down" if pct_change < 0 else "up"


def recent_news_titles_for_ticker(
    news_cache: NewsCache,
    ticker: str,
    *,
    limit: int = MAX_NEWS_IN_PROMPT,
) -> list[str]:
    """Collect the most recent ticker-tagged headlines as compact strings."""
    symbol = ticker.strip().upper()

    def timestamp(item: NewsItem) -> Any:
        return item.published_at or item.fetched_at

    matched = [item for item in news_cache.items if symbol in item.ticker_tags]
    matched.sort(key=timestamp, reverse=True)

    titles: list[str] = []
    for item in matched[:limit]:
        summary = item.summary.strip()
        if summary:
            clipped = summary[:_SUMMARY_CLIP].rstrip()
            titles.append(f"{item.title} — {clipped}")
        else:
            titles.append(item.title)
    return titles


def build_price_move_explanation_prompt(
    ticker: str,
    direction: str,
    pct_change: float,
    window: str,
    news_items: list[str],
    *,
    language: str = "en",
) -> str:
    """Build the reusable LLM prompt for a price-move explanation.

    `pct_change` is the move magnitude (use the absolute value); `direction`
    carries the up/down sign so the model does not have to infer it.
    """
    from bot.i18n import llm_language_clause

    if news_items:
        news_block = "\n".join(f"- {item}" for item in news_items)
        news_guidance = (
            "Base your reasoning on the news headlines below and general "
            "market context. Do not invent facts that are not supported."
        )
    else:
        news_block = "- (none provided)"
        news_guidance = (
            "No news was provided; focus on sector/market-level explanations "
            "and emphasize uncertainty. Do not fabricate company-specific events."
        )

    return (
        f"{_ROLE_INSTRUCTIONS}\n\n"
        f"Ticker: {ticker.strip().upper()}\n"
        f"Direction: {direction}\n"
        f"Move: {pct_change:.2f}% over {window}\n"
        f"{news_guidance}\n"
        f"Recent news:\n{news_block}\n\n"
        f"{llm_language_clause(language)}\n\n"
        "Respond with JSON only using this schema:\n"
        '{"drivers":["2-3 short likely drivers"],'
        '"sentiment":"positive|negative|mixed|uncertain",'
        '"assessment":"one-sentence overall assessment"}'
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


def _coerce_sentiment(value: Any) -> Sentiment:
    label = str(value).strip().lower()
    if label in {"positive", "negative", "mixed", "uncertain"}:
        return label  # type: ignore[return-value]
    return "uncertain"


def _coerce_drivers(value: Any) -> list[str]:
    if isinstance(value, list):
        drivers = [str(item).strip() for item in value if str(item).strip()]
    elif isinstance(value, str) and value.strip():
        drivers = [value.strip()]
    else:
        drivers = []
    return drivers[:3]


def _fallback_explanation(
    ticker: str,
    direction: str,
    magnitude: float,
    window: str,
    *,
    error: str | None,
) -> PriceMoveExplanation:
    return PriceMoveExplanation(
        ticker=ticker.strip().upper(),
        direction=direction,
        magnitude=magnitude,
        window=window,
        drivers=[],
        sentiment="uncertain",
        assessment="",
        source="fallback",
        error=error,
    )


def explain_price_move(
    llm: LlmClient,
    ticker: str,
    pct_change: float,
    window: str,
    news_items: list[str],
    *,
    company_name: str = "",
    sector: str = "",
    language: str = "en",
) -> PriceMoveExplanation:
    """Build the prompt, call the LLM, and return a structured explanation.

    Always returns a usable object: on missing config, LLM failure, or malformed
    output it falls back to a raw-price-only explanation. Side-effect free.
    """
    direction = direction_for_change(pct_change)
    magnitude = abs(pct_change)

    if not getattr(llm, "is_configured", False):
        return _fallback_explanation(
            ticker, direction, magnitude, window, error="LLM is not configured"
        )

    context_items = list(news_items)
    if company_name:
        context_items.insert(0, f"Company: {company_name}")
    if sector:
        context_items.insert(0, f"Sector: {sector}")

    prompt = build_price_move_explanation_prompt(
        ticker,
        direction,
        magnitude,
        window,
        context_items,
        language=language,
    )

    try:
        raw_response = llm.generate(prompt)
        payload = _extract_json_object(raw_response)
    except Exception as exc:
        logger.warning("Price-move explanation failed for %s: %s", ticker, exc)
        return _fallback_explanation(
            ticker, direction, magnitude, window, error=str(exc)
        )

    drivers = _coerce_drivers(payload.get("drivers"))
    assessment = str(payload.get("assessment", "")).strip()
    if not drivers and not assessment:
        return _fallback_explanation(
            ticker, direction, magnitude, window, error="empty model response"
        )

    return PriceMoveExplanation(
        ticker=ticker.strip().upper(),
        direction=direction,
        magnitude=magnitude,
        window=window,
        drivers=drivers,
        sentiment=_coerce_sentiment(payload.get("sentiment")),
        assessment=assessment,
        source="llm",
    )
