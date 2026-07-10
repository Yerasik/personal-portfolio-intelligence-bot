"""HKU ITS GenAI API settings (developer.hku.hk)."""

from __future__ import annotations

from config.settings import RuntimeSettings

DEFAULT_HKU_API_BASE_URL = "https://api.hku.hk"
DEFAULT_HKU_CLAUDE_MODELS = ("claude-sonnet-4.6",)
DEFAULT_HKU_OPENAI_API_VERSION = "2024-10-21"
DEFAULT_HKU_OPENAI_MODELS = ("gpt-5.5",)


def resolve_hku_api_settings(
    settings: RuntimeSettings,
) -> tuple[str, str | None, tuple[str, ...], tuple[str, ...], str]:
    """Resolve HKU gateway URL, API key, Claude models, OpenAI models, and api-version."""
    base_url = (settings.hku_api_base_url or DEFAULT_HKU_API_BASE_URL).rstrip("/")
    api_key = settings.hku_api_key.strip() if settings.hku_api_key else None
    claude_models = _resolve_claude_models(settings)
    openai_models = _resolve_openai_models(settings)
    api_version = settings.hku_openai_api_version or DEFAULT_HKU_OPENAI_API_VERSION
    return base_url, api_key, claude_models, openai_models, api_version


def _dedupe_models(models: list[str]) -> tuple[str, ...]:
    """Preserve order while removing empty/duplicate model names."""
    deduped: list[str] = []
    for model in models:
        name = model.strip()
        if name and name not in deduped:
            deduped.append(name)
    return tuple(deduped)


def _resolve_claude_models(settings: RuntimeSettings) -> tuple[str, ...]:
    """Parse Claude fallbacks: HKU_CLAUDE_MODELS, else primary + defaults."""
    raw = (settings.hku_claude_models or "").strip()
    if raw:
        return _dedupe_models([part for part in raw.split(",")])

    primary = (settings.hku_claude_model or DEFAULT_HKU_CLAUDE_MODELS[0]).strip()
    return _dedupe_models([primary])


def _resolve_openai_models(settings: RuntimeSettings) -> tuple[str, ...]:
    """Parse OpenAI fallbacks: HKU_OPENAI_MODELS, else primary + defaults."""
    raw = (settings.hku_openai_models or "").strip()
    if raw:
        return _dedupe_models([part for part in raw.split(",")])

    primary = (settings.hku_openai_model or DEFAULT_HKU_OPENAI_MODELS[0]).strip()
    return _dedupe_models([primary, *DEFAULT_HKU_OPENAI_MODELS[1:]])
