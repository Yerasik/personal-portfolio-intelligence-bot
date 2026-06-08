"""Shared language code normalization for storage and bot layers."""

from __future__ import annotations

SUPPORTED_LANGUAGES = frozenset({"en", "de", "zh", "ru"})


def normalize_language(code: str | None) -> str:
    """Map Telegram or user language codes to a supported language."""
    if not code:
        return "en"
    normalized = code.strip().lower().replace("_", "-")
    primary = normalized.split("-", 1)[0]
    if primary in SUPPORTED_LANGUAGES:
        return primary
    if primary.startswith("zh"):
        return "zh"
    if primary.startswith("de"):
        return "de"
    if primary.startswith("ru"):
        return "ru"
    return "en"
