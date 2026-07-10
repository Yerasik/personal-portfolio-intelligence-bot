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
_ANALYZE_HEADLINES = 5
_SUMMARY_CLIP = 160

_LANGUAGE_LABELS = {
    "en": "English",
    "de": "German",
    "zh": "Chinese",
    "ru": "Russian",
}

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
        from analysis.llm_format import format_llm_text

        lines: list[str] = []
        if self.drivers:
            lines.extend(f"• {format_llm_text(driver)}" for driver in self.drivers)
        else:
            lines.append(f"- {t('move_explanation_fallback', lang)}")
        assessment = format_llm_text(self.assessment) or t(
            "move_explanation_uncertain_assessment", lang
        )
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


@dataclass(frozen=True)
class AnalyzeTickerContext:
    """Inputs for the /analyze <ticker> LLM prompt."""

    ticker: str
    price: float | None
    change_pct: float | None
    week_52_low: float | None
    week_52_high: float | None
    cost_basis: float | None
    pnl_pct: float | None
    rsi: float | None
    headlines: list[str]
    language: str = "en"


def fetch_fifty_two_week_range(ticker: str) -> tuple[float | None, float | None]:
    """Return the 52-week low and high from yfinance, when available."""
    symbol = ticker.strip().upper()
    if not symbol:
        return None, None
    try:
        import yfinance as yf

        info = yf.Ticker(symbol).info or {}
        low = _coerce_optional_float(info.get("fiftyTwoWeekLow"))
        high = _coerce_optional_float(info.get("fiftyTwoWeekHigh"))
        return low, high
    except Exception as exc:
        logger.debug("52-week range fetch failed for %s: %s", symbol, exc)
        return None, None


def _coerce_optional_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_price(value: float | None, *, currency: str = "") -> str:
    if value is None:
        return "n/a"
    suffix = f" {currency}".rstrip()
    return f"{value:,.2f}{suffix}" if suffix else f"{value:,.2f}"


def _format_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.2f}%"


def _numbered_headlines(headlines: list[str], *, limit: int = _ANALYZE_HEADLINES) -> str:
    if not headlines:
        return "1. (none available)"
    return "\n   ".join(
        f"{index}. {headline}"
        for index, headline in enumerate(headlines[:limit], start=1)
    )


def build_analyze_ticker_prompt(context: AnalyzeTickerContext) -> str:
    """Build the /analyze <ticker> prompt for Ollama (qwen3:30b via HTTP API)."""
    from storage.languages import normalize_language

    language = _LANGUAGE_LABELS.get(
        normalize_language(context.language),
        "English",
    )
    symbol = context.ticker.strip().upper()
    return (
        f"System: You are a concise financial analyst. Respond in {language}. "
        f"Be specific, grounded, and under 150 words.\n\n"
        f"User context:\n"
        f"  - Ticker: {symbol}\n"
        f"  - Current price: {_format_price(context.price)}, "
        f"Change today: {_format_pct(context.change_pct)}\n"
        f"  - 52-week range: {_format_price(context.week_52_low)} - "
        f"{_format_price(context.week_52_high)}\n"
        f"  - Cost basis: {_format_price(context.cost_basis)}, "
        f"Unrealized P&L: {_format_pct(context.pnl_pct)}\n"
        f"  - RSI(14): {_format_price(context.rsi)}\n"
        f"  - Recent headlines (last 5, ticker-tagged):\n"
        f"   {_numbered_headlines(context.headlines)}\n\n"
        f"Instruction: Explain the price move in 3 bullet points. "
        f"Reference specific headlines where relevant. "
        f"End with one actionable observation (not a trade recommendation)."
    )


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


def _parse_analyze_response(text: str) -> tuple[list[str], str]:
    """Parse bullet points and a closing observation from model prose."""
    lines: list[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        stripped = re.sub(r"^[-*•]\s*", "", stripped)
        stripped = re.sub(r"^\d+\.\s*", "", stripped)
        if stripped:
            lines.append(stripped)

    if not lines:
        return [], ""

    if len(lines) >= 4:
        return lines[:3], lines[3]
    if len(lines) == 3:
        return lines[:3], ""
    if len(lines) == 2:
        return [lines[0]], lines[1]
    return lines, ""


def explain_ticker_for_analyze(
    llm: LlmClient,
    context: AnalyzeTickerContext,
    *,
    window: str = "today",
) -> PriceMoveExplanation:
    """Call Ollama with the /analyze prompt and return a structured explanation."""
    direction = direction_for_change(context.change_pct or 0.0)
    magnitude = abs(context.change_pct or 0.0)

    if not getattr(llm, "is_configured", False):
        return _fallback_explanation(
            context.ticker,
            direction,
            magnitude,
            window,
            error="LLM is not configured",
        )

    prompt = build_analyze_ticker_prompt(context)
    try:
        raw_response = llm.generate(prompt)
        drivers, assessment = _parse_analyze_response(raw_response)
    except Exception as exc:
        logger.warning(
            "Analyze ticker explanation failed for %s: %s",
            context.ticker,
            exc,
        )
        return _fallback_explanation(
            context.ticker,
            direction,
            magnitude,
            window,
            error=str(exc),
        )

    if not drivers and not assessment:
        return _fallback_explanation(
            context.ticker,
            direction,
            magnitude,
            window,
            error="empty model response",
        )

    return PriceMoveExplanation(
        ticker=context.ticker.strip().upper(),
        direction=direction,
        magnitude=magnitude,
        window=window,
        drivers=drivers,
        sentiment="uncertain",
        assessment=assessment,
        source="llm",
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
