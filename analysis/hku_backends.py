"""HTTP clients for HKU ITS GenAI APIs behind api.hku.hk."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_MAX_OUTPUT_TOKENS = 1024


def _extract_claude_text(payload: dict[str, Any]) -> str:
    """Pull assistant text from a Bedrock Converse response."""
    output = payload.get("output") or {}
    message = output.get("message") or {}
    content_blocks = message.get("content") or []
    for block in content_blocks:
        text = block.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
    raise ValueError("HKU Claude response has no assistant text")


def _extract_openai_text(payload: dict[str, Any]) -> str:
    """Pull assistant text from an OpenAI-compatible chat response."""
    choices = payload.get("choices") or []
    if not choices:
        raise ValueError("HKU OpenAI response has no choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("HKU OpenAI response has no assistant content")
    return content.strip()


def call_hku_claude_converse(
    *,
    client: httpx.Client,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    max_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
) -> str:
    """Invoke HKU AWS Bedrock Claude via the student Converse endpoint."""
    url = f"{base_url.rstrip('/')}/claude/student/model/{model}/converse"
    payload = {
        "messages": [
            {
                "role": "user",
                "content": [{"text": prompt}],
            }
        ],
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }
    headers = {
        "Content-Type": "application/json",
        "api-key": api_key,
    }
    logger.info("Calling HKU Claude model=%s", model)
    response = client.post(url, headers=headers, json=payload)
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise ValueError("HKU Claude response must be a JSON object")
    return _extract_claude_text(body)


def call_hku_openai_chat(
    *,
    client: httpx.Client,
    base_url: str,
    api_key: str,
    model: str,
    api_version: str,
    prompt: str,
    max_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
) -> str:
    """Invoke HKU Azure OpenAI chat completions."""
    url = (
        f"{base_url.rstrip('/')}/openai/deployments/{model}/chat/completions"
        f"?api-version={api_version}"
    )
    payload = {
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }
    headers = {
        "Content-Type": "application/json",
        "api-key": api_key,
    }
    logger.info("Calling HKU OpenAI model=%s", model)
    response = client.post(url, headers=headers, json=payload)
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise ValueError("HKU OpenAI response must be a JSON object")
    return _extract_openai_text(body)
