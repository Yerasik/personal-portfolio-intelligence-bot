"""Telegram MarkdownV2 escaping helpers."""

from __future__ import annotations

_MARKDOWN_V2_SPECIAL = frozenset(r"_*[]()~`>#+-=|{}.!")


def escape_markdown_v2(text: str) -> str:
    """Escape characters that are special in Telegram MarkdownV2."""
    return "".join(f"\\{char}" if char in _MARKDOWN_V2_SPECIAL else char for char in text)
