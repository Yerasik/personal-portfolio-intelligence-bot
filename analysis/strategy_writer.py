"""LLM helpers for ticker investment-strategy text and user announcements."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from analysis.llm import LlmClient
    from storage.models import TickerStrategy

logger = logging.getLogger(__name__)

_ROLE_INSTRUCTIONS = (
    "You are a cautious portfolio advisor. Turn developer notes into clear, "
    "user-friendly investment context. Never recommend buying, selling, or "
    "sizing trades. Frame ideas as rationale to review, not instructions."
)


@dataclass(frozen=True)
class GeneratedStrategy:
    """Structured strategy copy for storage and Telegram announcements."""

    strategy_text: str
    announcement_text: str


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


def build_strategy_prompt(
    ticker: str,
    developer_reasoning: str,
    *,
    shares: float,
    company_name: str = "",
    language: str = "en",
) -> str:
    """Build the LLM prompt for strategy and announcement copy."""
    from bot.i18n import llm_language_clause

    company_line = company_name.strip() or "unknown"
    return (
        f"{_ROLE_INSTRUCTIONS}\n\n"
        f"Ticker: {ticker.strip().upper()}\n"
        f"Company: {company_line}\n"
        f"Shares added: {shares:g}\n"
        f"Developer notes:\n{developer_reasoning.strip()}\n\n"
        f"{llm_language_clause(language)}\n\n"
        "Respond with JSON only using this schema:\n"
        '{"strategy_text":"2-4 sentences explaining the investment idea, '
        'key thesis, and what to watch",'
        '"announcement_text":"1-2 short sentences for a Telegram alert that a '
        'new holding was added, including the core idea"}'
    )


def build_announcement_prompt(
    ticker: str,
    strategy_text: str,
    *,
    shares: float,
    company_name: str = "",
    language: str = "en",
) -> str:
    """Build a short localized announcement prompt from stored strategy text."""
    from bot.i18n import llm_language_clause

    company_line = company_name.strip() or "unknown"
    return (
        f"{_ROLE_INSTRUCTIONS}\n\n"
        f"Ticker: {ticker.strip().upper()}\n"
        f"Company: {company_line}\n"
        f"Shares added: {shares:g}\n"
        f"Stored investment idea:\n{strategy_text.strip()}\n\n"
        f"{llm_language_clause(language)}\n\n"
        "Write one short Telegram alert (1-2 sentences) telling users a new "
        "holding was added and summarizing the idea. Respond with plain text only."
    )


def build_translate_strategy_prompt(
    ticker: str,
    strategy_text: str,
    *,
    language: str = "en",
) -> str:
    """Build a prompt that localizes stored strategy copy for /strategy display."""
    from bot.i18n import llm_language_clause

    return (
        f"{_ROLE_INSTRUCTIONS}\n\n"
        f"Ticker: {ticker.strip().upper()}\n"
        f"Investment idea to localize:\n{strategy_text.strip()}\n\n"
        f"{llm_language_clause(language)}\n\n"
        "Translate the investment idea faithfully for end users. "
        "Respond with plain text only (2-4 sentences)."
    )


def translate_strategy_text(
    llm: LlmClient,
    ticker: str,
    strategy_text: str,
    *,
    language: str = "en",
    enabled: bool = True,
) -> str:
    """Return strategy copy in the requested language."""
    source = strategy_text.strip()
    if not source:
        return source
    if not enabled or not getattr(llm, "is_configured", False):
        return source

    prompt = build_translate_strategy_prompt(ticker, source, language=language)
    try:
        response = llm.generate(prompt).strip()
        return response or source
    except Exception as exc:
        logger.warning(
            "Strategy translation failed for %s (%s): %s",
            ticker,
            language,
            exc,
        )
        return source


def build_strategy_text_by_language(
    llm: LlmClient,
    ticker: str,
    developer_reasoning: str,
    *,
    shares: float,
    company_name: str = "",
    languages: set[str],
    enabled: bool = True,
) -> tuple[GeneratedStrategy, dict[str, str]]:
    """Generate canonical English strategy plus per-language display text."""
    from bot.i18n import normalize_language

    normalized_langs = {normalize_language(lang) for lang in languages} or {"en"}
    generated_en = generate_ticker_strategy(
        llm,
        ticker,
        developer_reasoning,
        shares=shares,
        company_name=company_name,
        language="en",
        enabled=enabled,
    )
    by_language: dict[str, str] = {"en": generated_en.strategy_text}

    for lang in sorted(normalized_langs):
        if lang == "en":
            continue
        localized = generate_ticker_strategy(
            llm,
            ticker,
            developer_reasoning,
            shares=shares,
            company_name=company_name,
            language=lang,
            enabled=enabled,
        )
        by_language[lang] = localized.strategy_text

    return generated_en, by_language


def localized_strategy_text(
    llm: LlmClient,
    strategy: TickerStrategy,
    language: str,
    *,
    enabled: bool = True,
) -> str:
    """Return cached or freshly translated strategy text for one language."""
    from bot.i18n import normalize_language

    lang = normalize_language(language)
    cached = strategy.strategy_text_by_language.get(lang)
    if cached:
        return cached
    if lang == "en":
        return strategy.strategy_text
    return translate_strategy_text(
        llm,
        strategy.ticker,
        strategy.strategy_text,
        language=lang,
        enabled=enabled,
    )


def generate_ticker_strategy(
    llm: LlmClient,
    ticker: str,
    developer_reasoning: str,
    *,
    shares: float,
    company_name: str = "",
    language: str = "en",
    enabled: bool = True,
) -> GeneratedStrategy:
    """Create strategy and announcement copy from developer notes."""
    symbol = ticker.strip().upper()
    reasoning = developer_reasoning.strip()
    if not reasoning:
        raise ValueError("Developer reasoning is empty")

    if not enabled or not getattr(llm, "is_configured", False):
        return GeneratedStrategy(strategy_text=reasoning, announcement_text=reasoning)

    prompt = build_strategy_prompt(
        symbol,
        reasoning,
        shares=shares,
        company_name=company_name,
        language=language,
    )
    try:
        raw_response = llm.generate(prompt)
        payload = _extract_json_object(raw_response)
        strategy_text = str(payload.get("strategy_text", "")).strip()
        announcement_text = str(payload.get("announcement_text", "")).strip()
        if not strategy_text:
            strategy_text = reasoning
        if not announcement_text:
            announcement_text = strategy_text
        return GeneratedStrategy(
            strategy_text=strategy_text,
            announcement_text=announcement_text,
        )
    except Exception as exc:
        logger.warning("Strategy generation failed for %s: %s", symbol, exc)
        return GeneratedStrategy(strategy_text=reasoning, announcement_text=reasoning)


def generate_strategy_announcement(
    llm: LlmClient,
    ticker: str,
    strategy_text: str,
    *,
    shares: float,
    company_name: str = "",
    language: str = "en",
    enabled: bool = True,
) -> str:
    """Localize a short new-holding announcement for one user language."""
    if not enabled or not getattr(llm, "is_configured", False):
        return strategy_text

    prompt = build_announcement_prompt(
        ticker,
        strategy_text,
        shares=shares,
        company_name=company_name,
        language=language,
    )
    try:
        response = llm.generate(prompt).strip()
        return response or strategy_text
    except Exception as exc:
        logger.warning(
            "Strategy announcement failed for %s (%s): %s",
            ticker,
            language,
            exc,
        )
        return strategy_text


def build_sell_prompt(
    ticker: str,
    developer_reasoning: str,
    *,
    shares_sold: float,
    sell_price: float,
    company_name: str = "",
    language: str = "en",
) -> str:
    """Build the LLM prompt for a sell announcement."""
    from bot.i18n import llm_language_clause

    company_line = company_name.strip() or "unknown"
    return (
        f"{_ROLE_INSTRUCTIONS}\n\n"
        f"Ticker: {ticker.strip().upper()}\n"
        f"Company: {company_line}\n"
        f"Shares sold: {shares_sold:g}\n"
        f"Sell price per share: {sell_price:g}\n"
        f"Developer notes:\n{developer_reasoning.strip()}\n\n"
        f"{llm_language_clause(language)}\n\n"
        "Respond with JSON only using this schema:\n"
        '{"announcement_text":"1-2 short sentences for a Telegram alert that '
        'shares were sold, including the core rationale"}'
    )


def build_sell_announcement_prompt(
    ticker: str,
    announcement_en: str,
    *,
    shares_sold: float,
    sell_price: float,
    company_name: str = "",
    language: str = "en",
) -> str:
    """Build a short localized sell-announcement prompt from English copy."""
    from bot.i18n import llm_language_clause

    company_line = company_name.strip() or "unknown"
    return (
        f"{_ROLE_INSTRUCTIONS}\n\n"
        f"Ticker: {ticker.strip().upper()}\n"
        f"Company: {company_line}\n"
        f"Shares sold: {shares_sold:g}\n"
        f"Sell price per share: {sell_price:g}\n"
        f"English announcement:\n{announcement_en.strip()}\n\n"
        f"{llm_language_clause(language)}\n\n"
        "Write one short Telegram alert (1-2 sentences) telling users shares "
        "were sold and summarizing the rationale. Respond with plain text only."
    )


def generate_sell_announcement_from_reasoning(
    llm: LlmClient,
    ticker: str,
    developer_reasoning: str,
    *,
    shares_sold: float,
    sell_price: float,
    company_name: str = "",
    language: str = "en",
    enabled: bool = True,
) -> str:
    """Create sell announcement copy from developer notes."""
    symbol = ticker.strip().upper()
    reasoning = developer_reasoning.strip()
    if not reasoning:
        raise ValueError("Developer reasoning is empty")

    if not enabled or not getattr(llm, "is_configured", False):
        return reasoning

    prompt = build_sell_prompt(
        symbol,
        reasoning,
        shares_sold=shares_sold,
        sell_price=sell_price,
        company_name=company_name,
        language=language,
    )
    try:
        raw_response = llm.generate(prompt)
        payload = _extract_json_object(raw_response)
        announcement_text = str(payload.get("announcement_text", "")).strip()
        return announcement_text or reasoning
    except Exception as exc:
        logger.warning("Sell announcement generation failed for %s: %s", symbol, exc)
        return reasoning


def generate_sell_announcement(
    llm: LlmClient,
    ticker: str,
    announcement_en: str,
    *,
    shares_sold: float,
    sell_price: float,
    company_name: str = "",
    language: str = "en",
    enabled: bool = True,
) -> str:
    """Localize a short sell announcement for one user language."""
    source = announcement_en.strip()
    if not source:
        return source
    if not enabled or not getattr(llm, "is_configured", False):
        return source

    prompt = build_sell_announcement_prompt(
        ticker,
        source,
        shares_sold=shares_sold,
        sell_price=sell_price,
        company_name=company_name,
        language=language,
    )
    try:
        response = llm.generate(prompt).strip()
        return response or source
    except Exception as exc:
        logger.warning(
            "Sell announcement localization failed for %s (%s): %s",
            ticker,
            language,
            exc,
        )
        return source
