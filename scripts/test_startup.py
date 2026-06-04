#!/usr/bin/env python3
"""Smoke test for startup validation helpers."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import RuntimeSettings
from config.startup import StartupError, validate_telegram_credentials


class SettingsStub:
    def __init__(self, token: str, chat_id: str) -> None:
        self.telegram_bot_token = token
        self.telegram_chat_id = chat_id


def run_test() -> None:
    try:
        validate_telegram_credentials(
            SettingsStub("your_bot_token_here", "12345")  # type: ignore[arg-type]
        )
    except StartupError:
        pass
    else:
        raise AssertionError("placeholder token should fail validation")

    validate_telegram_credentials(
        SettingsStub("123456:real-token", "12345")  # type: ignore[arg-type]
    )

    try:
        validate_telegram_credentials(
            SettingsStub("123456:real-token", "your_chat_id_here")  # type: ignore[arg-type]
        )
    except StartupError:
        pass
    else:
        raise AssertionError("placeholder chat id should fail validation")

    print("Startup validation checks passed.")


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
