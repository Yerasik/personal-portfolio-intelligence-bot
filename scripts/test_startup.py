#!/usr/bin/env python3
"""Smoke test for startup validation helpers."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.startup import (
    StartupError,
    bootstrap_users_if_needed,
    validate_telegram_credentials,
)
from storage.paths import resolve_data_paths
from storage.repository import DataRepository


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

    temp_dir = Path(tempfile.mkdtemp(prefix="startup-test-"))
    try:
        repository = DataRepository(resolve_data_paths(temp_dir))
        try:
            bootstrap_users_if_needed(
                repository,
                SettingsStub("123456:real-token", "your_chat_id_here"),  # type: ignore[arg-type]
            )
        except StartupError:
            pass
        else:
            raise AssertionError("placeholder chat id should fail bootstrap")

        bootstrap_users_if_needed(
            repository,
            SettingsStub("123456:real-token", "12345"),  # type: ignore[arg-type]
        )
        users = repository.load_users()
        if len(users.users) != 1 or users.users[0].chat_id != 12345:
            raise AssertionError("bootstrap should create one developer user")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    print("Startup validation checks passed.")


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
