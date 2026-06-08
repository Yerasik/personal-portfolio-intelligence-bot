#!/usr/bin/env python3
"""Smoke tests for multi-user access control and localization."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.rules import AlertCandidate
from bot.formatter import format_urgent_alert
from bot.handlers import is_authorized
from bot.i18n import t
from storage.models import BotUser, BotUsers
from storage.paths import resolve_data_paths
from storage.repository import DataRepository


class FakeUpdate:
    def __init__(self, chat_id: int) -> None:
        self.effective_chat = type("Chat", (), {"id": chat_id})()


def run_test() -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="users-test-"))
    print(f"Using temp data dir: {temp_dir}")

    try:
        paths = resolve_data_paths(temp_dir)
        repository = DataRepository(paths)
        repository.save_users(
            BotUsers(
                users=[
                    BotUser(chat_id=111, language="en", role="developer"),
                    BotUser(chat_id=222, language="de", role="ordinary"),
                ]
            )
        )

        if not is_authorized(FakeUpdate(111), repository):
            raise AssertionError("developer chat should be authorized")
        if not is_authorized(FakeUpdate(222), repository):
            raise AssertionError("ordinary chat should be authorized")
        if is_authorized(FakeUpdate(999), repository):
            raise AssertionError("unknown chat should be rejected")

        if not repository.is_developer(111):
            raise AssertionError("chat 111 should be developer")
        if repository.is_developer(222):
            raise AssertionError("chat 222 should not be developer")

        ok, lang = repository.set_user_language(222, "ru")
        if not ok or lang != "ru":
            raise AssertionError("set_user_language failed for ru")
        if repository.user_language(222) != "ru":
            raise AssertionError("Russian language not persisted")

        ok, lang = repository.set_user_language(222, "zh")
        if not ok or lang != "zh":
            raise AssertionError("set_user_language failed")
        if repository.user_language(222) != "zh":
            raise AssertionError("language not persisted")

        ok, result = repository.add_user(333, role="ordinary", language="de")
        if not ok or result != "added":
            raise AssertionError("add_user failed")
        ok, result = repository.add_user(333)
        if ok or result != "exists":
            raise AssertionError("duplicate add_user should fail")

        ok, result = repository.remove_user(333)
        if not ok or result != "removed":
            raise AssertionError("remove_user failed")

        alert = AlertCandidate(
            id="a1",
            type="price_drop",
            ticker="AAPL",
            industry=None,
            urgency="urgent",
            title="AAPL down 8.0% today",
            explanation="AAPL fell 8.00% since the last market fetch.",
            created_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        )
        en_text = format_urgent_alert(alert, lang="en")
        de_text = format_urgent_alert(alert, lang="de")
        ru_text = format_urgent_alert(alert, lang="ru")
        if "URGENT ALERT" not in en_text:
            raise AssertionError("English alert header missing")
        if "DRINGENDE WARNUNG" not in de_text:
            raise AssertionError("German alert header missing")
        if "СРОЧНОЕ ПРЕДУПРЕЖДЕНИЕ" not in ru_text:
            raise AssertionError("Russian alert header missing")
        if alert.title not in en_text or alert.title not in de_text or alert.title not in ru_text:
            raise AssertionError("alert body should be shared across languages")

        if t("developer_only", "de") not in t("developer_only", "de"):
            raise AssertionError("translation lookup failed")

        seeded = repository.bootstrap_users_if_empty(999)
        if len(seeded.users) != 2:
            raise AssertionError("bootstrap should not overwrite existing users")

        print("Multi-user checks passed.")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
