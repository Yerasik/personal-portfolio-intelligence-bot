"""Portfolio-aware free-text chat prompts and replies."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from analysis.llm import (
    LlmClient,
    LlmGenerationError,
    _format_holdings,
    _format_news,
    _format_prices,
    _SYSTEM_INSTRUCTIONS,
    select_relevant_news,
)
from analysis.llm_format import format_llm_text
from analysis.industries import build_news_focus_industries
from bot.i18n import llm_language_clause
from storage.models import (
    AppConfig,
    BotState,
    ChatTurn,
    LlmProvider,
    NewsCache,
    Portfolio,
)

logger = logging.getLogger(__name__)

MAX_CHAT_NEWS = 8
MAX_HISTORY_CHARS = 4000


@dataclass(frozen=True)
class PortfolioChatResult:
    """Plain-text chat reply from a chosen LLM provider."""

    text: str
    source: LlmProvider | str
    error: str | None = None


def _format_history(turns: list[ChatTurn]) -> str:
    """Format recent chat turns for the prompt, truncated if needed."""
    if not turns:
        return "- None yet"
    lines: list[str] = []
    for turn in turns:
        label = "User" if turn.role == "user" else "Assistant"
        lines.append(f"{label}: {turn.content.strip()}")
    text = "\n".join(lines)
    if len(text) <= MAX_HISTORY_CHARS:
        return text
    return text[-MAX_HISTORY_CHARS:]


def build_portfolio_chat_prompt(
    *,
    user_message: str,
    portfolio: Portfolio,
    app_config: AppConfig,
    state: BotState,
    news_cache: NewsCache,
    history: list[ChatTurn],
    ticker_to_industry: dict[str, str] | None = None,
    language: str = "en",
) -> str:
    """Build a chat prompt with holdings, price moves, and relevant news."""
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
        limit=MAX_CHAT_NEWS,
    )
    cash_lines = (
        f"- HKD: {portfolio.cash:g}\n"
        f"- USD: {portfolio.cash_usd:g}\n"
        f"- JPY: {portfolio.cash_jpy:g}"
    )

    return (
        f"{_SYSTEM_INSTRUCTIONS}\n\n"
        "You are chatting with an authorized portfolio user. "
        "Answer their question using the portfolio context below. "
        "Be concise and practical. Do not invent holdings or prices. "
        "If something is unknown from the context, say so.\n\n"
        "Portfolio context:\n"
        f"Holdings:\n{_format_holdings(portfolio)}\n"
        f"Cash balances:\n{cash_lines}\n"
        f"Focus industries: {industries}\n"
        f"Latest prices and daily moves:\n{_format_prices(state, portfolio)}\n"
        f"Most relevant recent news:\n{_format_news(news_items)}\n\n"
        f"Recent conversation:\n{_format_history(history)}\n\n"
        f"{llm_language_clause(language)}\n\n"
        f"User message:\n{user_message.strip()}\n\n"
        "Respond in plain text (not JSON). Use short paragraphs or bullets when helpful."
    )


def answer_portfolio_chat(
    llm: LlmClient,
    *,
    user_message: str,
    portfolio: Portfolio,
    app_config: AppConfig,
    state: BotState,
    news_cache: NewsCache,
    history: list[ChatTurn],
    provider: LlmProvider,
    ticker_to_industry: dict[str, str] | None = None,
    language: str = "en",
) -> PortfolioChatResult:
    """Generate a portfolio-aware chat reply with the user's chosen provider."""
    if not user_message.strip():
        return PortfolioChatResult(
            text="",
            source=provider,
            error="empty_message",
        )

    prompt = build_portfolio_chat_prompt(
        user_message=user_message,
        portfolio=portfolio,
        app_config=app_config,
        state=state,
        news_cache=news_cache,
        history=history,
        ticker_to_industry=ticker_to_industry,
        language=language,
    )

    try:
        raw = llm.generate(prompt, provider=provider)
    except LlmGenerationError as exc:
        logger.warning("Portfolio chat LLM failed (%s): %s", provider, exc)
        return PortfolioChatResult(
            text="",
            source=provider,
            error=str(exc),
        )
    except Exception as exc:
        logger.exception("Unexpected portfolio chat error")
        return PortfolioChatResult(
            text="",
            source=provider,
            error=f"Unexpected LLM error: {exc}",
        )

    text = format_llm_text(raw.strip())
    if not text:
        return PortfolioChatResult(
            text="",
            source=llm.last_source or provider,
            error="empty_response",
        )
    return PortfolioChatResult(
        text=text,
        source=llm.last_source or provider,
    )
