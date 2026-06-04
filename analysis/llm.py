"""Ollama-backed summarization (to be implemented later)."""

from config.settings import RuntimeSettings


class LlmClient:
    """Thin wrapper around the local Ollama HTTP API."""

    def __init__(self, settings: RuntimeSettings) -> None:
        self._base_url = settings.ollama_base_url
        self._model = settings.ollama_model

    @property
    def is_configured(self) -> bool:
        return bool(self._base_url and self._model)
