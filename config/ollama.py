"""Ollama endpoint resolution (environment variables with config.json fallback)."""

from __future__ import annotations

from config.settings import RuntimeSettings
from storage.models import AppConfig

DEFAULT_OLLAMA_BASE_URL = "http://ollama:11434"
DEFAULT_OLLAMA_MODEL = "qwen3:30b"


def resolve_ollama_settings(
    settings: RuntimeSettings,
    app_config: AppConfig | None = None,
) -> tuple[str, str]:
    """Resolve Ollama base URL and model from env vars, then config, then defaults."""
    config_base = app_config.ollama_base_url.strip() if app_config else ""
    config_model = app_config.ollama_model.strip() if app_config else ""

    base_url = settings.ollama_base_url or config_base or DEFAULT_OLLAMA_BASE_URL
    model = settings.ollama_model or config_model or DEFAULT_OLLAMA_MODEL
    return base_url.rstrip("/"), model
