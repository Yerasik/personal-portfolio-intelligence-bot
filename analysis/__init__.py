"""Rules-based and LLM-assisted portfolio analysis."""

from analysis.llm import LlmAdvisoryResult, LlmClient, build_advisory_prompt
from analysis.move_explainer import (
    AnalyzeTickerContext,
    PriceMoveExplanation,
    build_analyze_ticker_prompt,
    build_price_move_explanation_prompt,
    explain_price_move,
    explain_ticker_for_analyze,
    recent_news_titles_for_ticker,
)
from analysis.news_summarizer import NewsSummary, summarize_news
from analysis.rules import AlertCandidate, RulesEngine
from analysis.summarizer import Summarizer

__all__ = [
    "AlertCandidate",
    "AnalyzeTickerContext",
    "LlmAdvisoryResult",
    "LlmClient",
    "NewsSummary",
    "PriceMoveExplanation",
    "RulesEngine",
    "Summarizer",
    "build_advisory_prompt",
    "build_analyze_ticker_prompt",
    "build_price_move_explanation_prompt",
    "explain_price_move",
    "explain_ticker_for_analyze",
    "recent_news_titles_for_ticker",
    "summarize_news",
]
