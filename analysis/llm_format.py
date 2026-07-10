"""Normalize LLM prose for readable Telegram plain-text output."""

from __future__ import annotations

import re

_MULTI_BLANK_LINES = re.compile(r"\n{3,}")
_MARKDOWN_HEADER = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")
_UNDERLINE = re.compile(r"__([^_]+)__")
_LIST_MARKER = re.compile(r"^(\s*)([-*•]|\d+[.)])\s+")


def format_llm_text(text: str) -> str:
    """Preserve paragraphs and lists; lightly clean markdown for plain text."""
    if not text or not text.strip():
        return ""

    cleaned = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    cleaned = _MARKDOWN_HEADER.sub("", cleaned)
    cleaned = _BOLD.sub(r"\1", cleaned)
    cleaned = _ITALIC.sub(r"\1", cleaned)
    cleaned = _UNDERLINE.sub(r"\1", cleaned)

    expanded: list[str] = []
    for line in cleaned.split("\n"):
        expanded.extend(_expand_inline_bullets(line))

    normalized: list[str] = []
    for line in expanded:
        stripped = line.strip()
        if not stripped:
            if normalized and normalized[-1] != "":
                normalized.append("")
            continue
        match = _LIST_MARKER.match(stripped)
        if match:
            marker = match.group(2)
            body = stripped[match.end() :].strip()
            if marker[0].isdigit():
                normalized.append(f"{marker[0]}. {body}")
            else:
                normalized.append(f"• {body}")
            continue
        normalized.append(stripped)

    return _MULTI_BLANK_LINES.sub("\n\n", "\n".join(normalized)).strip()


def extend_formatted_llm_lines(lines: list[str], text: str) -> None:
    """Append formatted LLM text to a message line list, one line per row."""
    formatted = format_llm_text(text)
    if not formatted:
        return
    if lines and lines[-1] != "":
        lines.append("")
    lines.extend(formatted.split("\n"))


def _expand_inline_bullets(line: str) -> list[str]:
    """Split dense single-line bullet lists into separate lines."""
    stripped = line.strip()
    if not stripped or stripped.startswith(("-", "•", "*")):
        return [line]
    if re.match(r"^\d+[.)]\s", stripped):
        return [line]

    parts = re.split(r"\s+-\s+", stripped)
    if len(parts) < 3:
        return [line]

    head = parts[0].rstrip(":").strip()
    rows = [f"{head}:"] if head else []
    rows.extend(f"• {part.strip()}" for part in parts[1:] if part.strip())
    return rows
