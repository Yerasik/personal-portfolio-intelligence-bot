"""Bundle the rules engine and optional LLM client for the daily summary job."""

from dataclasses import dataclass

from analysis.llm import LlmClient
from analysis.rules import RulesEngine
from storage.models import AppConfig


@dataclass(frozen=True)
class Summarizer:
    """Hold the analysis dependencies used to build a daily summary."""

    app_config: AppConfig
    rules: RulesEngine
    llm: LlmClient
