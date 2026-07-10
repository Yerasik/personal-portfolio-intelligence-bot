#!/usr/bin/env python3
"""Smoke test for HKU ITS GenAI APIs (developer.hku.hk).

Uses your subscription primary key against the HKU API gateway. A successful
run sends one short chat completion and prints the model reply.

Examples:
  export HKU_API_KEY='your-primary-key'
  python scripts/test_hku_api.py

  python scripts/test_hku_api.py --key 'your-primary-key' --model gpt-4.1-nano

  docker compose run --rm portfolio-bot python scripts/test_hku_api.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.llm_format import format_llm_text

DEFAULT_BASE_URL = "https://api.hku.hk"
DEFAULT_API = "claude"
DEFAULT_MODEL = "claude-sonnet-4.6"
DEFAULT_API_VERSION = "2024-10-21"
DEFAULT_TIMEOUT_SECONDS = 60.0
CLAUDE_MODELS = (
    "claude-haiku-4.5",
    "claude-sonnet-4.6",
    "claude-sonnet-5",
    "claude-opus-4.6",
)
ENV_KEY_NAMES = ("HKU_API_KEY", "HKU_APIM_SUBSCRIPTION_KEY", "HKU_PRIMARY_KEY")


def _load_dotenv_key() -> str | None:
    """Read HKU_API_KEY from the project .env without overriding the shell."""
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name.strip() != "HKU_API_KEY":
            continue
        return value.strip().strip("'\"")
    return None


def resolve_api_key(cli_key: str | None) -> str:
    """Resolve the subscription key from CLI, environment, or .env."""
    if cli_key:
        return cli_key.strip()
    for name in ENV_KEY_NAMES:
        value = os.getenv(name)
        if value:
            return value.strip()
    dotenv_value = _load_dotenv_key()
    if dotenv_value:
        return dotenv_value
    raise SystemExit(
        "No API key found. Set HKU_API_KEY in .env, export it, or pass --key."
    )


def mask_key(key: str) -> str:
    """Return a redacted preview of the subscription key."""
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}...{key[-4:]}"


def build_request_url(base_url: str, api: str, model: str, api_version: str) -> str:
    """Build the request URL for the selected HKU GenAI API."""
    base = base_url.rstrip("/")
    if api == "claude":
        return f"{base}/claude/student/model/{model}/converse"
    if api == "openai":
        return (
            f"{base}/openai/deployments/{model}/chat/completions"
            f"?api-version={api_version}"
        )
    raise ValueError(f"unsupported API: {api}")


def build_headers(api_key: str) -> dict[str, str]:
    """Headers accepted by api.hku.hk (api-key, not Ocp-Apim-Subscription-Key)."""
    return {
        "Content-Type": "application/json",
        "api-key": api_key,
    }


def extract_assistant_text(api: str, payload: dict[str, Any]) -> str:
    """Pull assistant text from an OpenAI or Bedrock Converse response."""
    if api == "claude":
        output = payload.get("output") or {}
        message = output.get("message") or {}
        content_blocks = message.get("content") or []
        for block in content_blocks:
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
        raise ValueError("response has no assistant text content")

    choices = payload.get("choices") or []
    if not choices:
        raise ValueError("response has no choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("response choice has no assistant content")
    return content.strip()


def format_http_error(response: httpx.Response) -> str:
    """Format APIM / gateway error bodies for terminal output."""
    try:
        body = response.json()
        return json.dumps(body, indent=2, ensure_ascii=False)
    except json.JSONDecodeError:
        text = response.text.strip()
        return text or f"HTTP {response.status_code} with empty body"


def build_request_payload(api: str, prompt: str) -> dict[str, Any]:
    """Build the JSON body for the selected HKU GenAI API."""
    if api == "claude":
        return {
            "messages": [
                {
                    "role": "user",
                    "content": [{"text": prompt}],
                }
            ],
            "max_tokens": 64,
            "temperature": 0,
        }
    return {
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "max_tokens": 64,
        "temperature": 0,
    }


def test_chat_completion(
    *,
    client: httpx.Client,
    base_url: str,
    api: str,
    api_key: str,
    model: str,
    api_version: str,
    prompt: str,
) -> dict[str, Any]:
    """Send one chat completion request and return the parsed JSON body."""
    url = build_request_url(base_url, api, model, api_version)
    payload = build_request_payload(api, prompt)
    response = client.post(url, headers=build_headers(api_key), json=payload)
    if response.is_error:
        raise RuntimeError(
            f"Chat request failed ({response.status_code}):\n"
            f"{format_http_error(response)}"
        )
    return response.json()


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Test HKU ITS GenAI API access with your subscription key.",
    )
    parser.add_argument(
        "--key",
        help="Primary subscription key (overrides HKU_API_KEY env / .env).",
    )
    parser.add_argument(
        "--api",
        choices=("claude", "openai"),
        default=os.getenv("HKU_API_KIND", DEFAULT_API),
        help=f"API product to test: claude or openai (default: {DEFAULT_API}).",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("HKU_API_BASE_URL", DEFAULT_BASE_URL),
        help=f"API gateway base URL (default: {DEFAULT_BASE_URL}).",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("HKU_API_MODEL", DEFAULT_MODEL),
        help=f"Deployment / model name (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--api-version",
        default=os.getenv("HKU_API_VERSION", DEFAULT_API_VERSION),
        help=f"Azure OpenAI api-version query param (default: {DEFAULT_API_VERSION}).",
    )
    parser.add_argument(
        "--prompt",
        default="Reply with exactly: HKU API test OK",
        help="User message sent to the model (ignored with --chat).",
    )
    parser.add_argument(
        "--chat",
        action="store_true",
        help="Interactive chat loop. Type 'exit' or Ctrl-D to quit.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"HTTP timeout in seconds (default: {DEFAULT_TIMEOUT_SECONDS}).",
    )
    return parser.parse_args()


def print_usage(api: str, usage: dict[str, Any]) -> None:
    """Print token usage for the selected API response format."""
    if not usage:
        return
    if api == "claude":
        print(
            f"[tokens: in={usage.get('inputTokens', '?')},"
            f" out={usage.get('outputTokens', '?')},"
            f" total={usage.get('totalTokens', '?')}]"
        )
        return
    print(
        f"[tokens: prompt={usage.get('prompt_tokens', '?')},"
        f" completion={usage.get('completion_tokens', '?')},"
        f" total={usage.get('total_tokens', '?')}]"
    )


def run_interactive_chat(
    *,
    client: httpx.Client,
    args: argparse.Namespace,
    api_key: str,
) -> int:
    """Run a simple REPL that sends one question at a time to the model."""
    print("HKU Claude chat (type 'exit' to quit)")
    print(f"Model: {args.model}")
    print()

    while True:
        try:
            user_input = input("You: ").strip()
        except EOFError:
            print()
            break
        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit", "q"}:
            break

        try:
            payload = test_chat_completion(
                client=client,
                base_url=args.base_url,
                api=args.api,
                api_key=api_key,
                model=args.model,
                api_version=args.api_version,
                prompt=user_input,
            )
            reply = extract_assistant_text(args.api, payload)
        except (httpx.RequestError, RuntimeError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            continue

        print(f"\nClaude: {format_llm_text(reply)}\n")
        print_usage(args.api, payload.get("usage") or {})
        print()

    return 0


def main() -> int:
    """Run the smoke test or interactive chat."""
    args = parse_args()
    api_key = resolve_api_key(args.key)

    if args.chat:
        print(f"Key: {mask_key(api_key)}")
        with httpx.Client(timeout=args.timeout) as client:
            return run_interactive_chat(client=client, args=args, api_key=api_key)

    print("HKU GenAI API smoke test")
    print(f"  API:         {args.api}")
    print(f"  Gateway:     {args.base_url.rstrip('/')}")
    print(f"  Model:       {args.model}")
    if args.api == "openai":
        print(f"  API version: {args.api_version}")
    print(f"  Key:         {mask_key(api_key)}")
    print()

    with httpx.Client(timeout=args.timeout) as client:
        try:
            payload = test_chat_completion(
                client=client,
                base_url=args.base_url,
                api=args.api,
                api_key=api_key,
                model=args.model,
                api_version=args.api_version,
                prompt=args.prompt,
            )
        except httpx.RequestError as exc:
            print(f"FAILED: network error — {exc}", file=sys.stderr)
            return 1
        except RuntimeError as exc:
            print(f"FAILED: {exc}", file=sys.stderr)
            tips = [
                "- Copy the primary key from https://developer.hku.hk/profile",
            ]
            if args.api == "claude":
                tips.extend(
                    [
                        "- Confirm aws-bedrock-claude-service-api-preview-for-students is approved.",
                        f"- Valid models: {', '.join(CLAUDE_MODELS)}",
                        "- Try another model, e.g. --model claude-haiku-4.5",
                    ]
                )
            else:
                tips.extend(
                    [
                        "- Confirm your student-genai-services subscription is approved.",
                        "- Try another model, e.g. --model gpt-4.1-nano",
                    ]
                )
            print("\nTips:", *tips, sep="\n", file=sys.stderr)
            return 1

    try:
        reply = extract_assistant_text(args.api, payload)
    except ValueError as exc:
        print(f"FAILED: unexpected response shape — {exc}", file=sys.stderr)
        print(json.dumps(payload, indent=2, ensure_ascii=False), file=sys.stderr)
        return 1

    usage = payload.get("usage") or {}
    print("SUCCESS — API key works.")
    print("Model reply:")
    print(format_llm_text(reply))
    print_usage(args.api, usage)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
