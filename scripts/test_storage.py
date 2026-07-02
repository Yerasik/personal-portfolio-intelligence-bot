#!/usr/bin/env python3
"""Smoke test for the JSON storage layer."""

from __future__ import annotations

import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from storage.json_store import JsonStorageError, JsonStore
from storage.models import BotState, NewsCache, Portfolio, Position
from storage.paths import resolve_data_paths
from storage.repository import DataRepository


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_tests() -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="storage-test-"))
    print(f"Using temp data dir: {temp_dir}")

    try:
        paths = resolve_data_paths(temp_dir)
        store = JsonStore()
        repo = DataRepository(paths, store)

        # Missing files initialize from defaults.
        config = repo.load_config()
        _assert(config.timezone == "Asia/Hong_Kong", "default config timezone")
        _assert(paths.config.exists(), "config.json created")

        portfolio = repo.load_portfolio()
        _assert(portfolio.positions == [], "default empty portfolio")

        state = repo.load_state()
        _assert(state.pending_alerts == [], "default empty alerts")

        cache = repo.load_news_cache()
        _assert(cache.items == [], "default empty news cache")

        # Round-trip save/load.
        portfolio = Portfolio(
            positions=[
                Position(ticker="AAPL", shares=10, cost_basis=150.0, notes="core")
            ],
            notes="test portfolio",
        )
        repo.save_portfolio(portfolio)
        loaded = repo.load_portfolio()
        _assert(loaded.positions[0].ticker == "AAPL", "portfolio round-trip")
        _assert(loaded.positions[0].shares == 10, "migrated shares")
        _assert(loaded.positions[0].blended_cost_basis == 150.0, "migrated cost")
        _assert(len(loaded.positions[0].lots) == 1, "single lot after migration")
        _assert(loaded.positions[0].lots[0].date == "unknown", "legacy lot date")

        raw = paths.portfolio.read_text(encoding="utf-8")
        _assert('"lots"' in raw, "portfolio persisted with lots")
        _assert('"cost_basis"' not in raw, "legacy cost_basis not persisted")

        state = BotState(last_digest_at=datetime.now(tz=UTC))
        repo.save_state(state)
        loaded_state = repo.load_state()
        _assert(loaded_state.last_digest_at is not None, "state round-trip")

        cache = NewsCache(updated_at=datetime.now(tz=UTC))
        repo.save_news_cache(cache)
        loaded_cache = repo.load_news_cache()
        _assert(loaded_cache.updated_at is not None, "news cache round-trip")

        # Malformed JSON raises a clear error.
        paths.state.write_text("{not valid json", encoding="utf-8")
        try:
            repo.load_state()
        except JsonStorageError as exc:
            _assert("Malformed JSON" in str(exc), "malformed json message")
        else:
            raise AssertionError("expected JsonStorageError for malformed JSON")

        # Invalid schema raises a clear error.
        paths.portfolio.write_text('{"positions": "bad"}', encoding="utf-8")
        try:
            repo.load_portfolio()
        except JsonStorageError as exc:
            _assert("Invalid schema" in str(exc), "invalid schema message")
        else:
            raise AssertionError("expected JsonStorageError for invalid schema")

        print("All storage checks passed.")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    try:
        run_tests()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
