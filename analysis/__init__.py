"""Rules-based and LLM-assisted portfolio analysis."""

from analysis.llm import LlmAdvisoryResult, LlmClient, build_advisory_prompt
from analysis.move_explainer import (
    PriceMoveExplanation,
    build_price_move_explanation_prompt,
    explain_price_move,
    recent_news_titles_for_ticker,
)
from analysis.rules import AlertCandidate, RulesEngine
from analysis.summarizer import Summarizer

__all__ = [
    "AlertCandidate",
    "LlmAdvisoryResult",
    "LlmClient",
    "PriceMoveExplanation",
    "RulesEngine",
    "Summarizer",
    "build_advisory_prompt",
    "build_price_move_explanation_prompt",
    "explain_price_move",
    "recent_news_titles_for_ticker",
]
