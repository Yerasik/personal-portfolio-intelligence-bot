#!/usr/bin/env python3
"""Smoke test for automatic per-ticker news discovery."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collectors.auto_news_discovery import AutoNewsDiscovery
from storage.paths import resolve_data_paths
from storage.repository import DataRepository


def run_test() -> None:
    data_dir = os.environ.get("DATA_DIR", str(ROOT / "data"))
    paths = resolve_data_paths(data_dir)
    repository = DataRepository(paths)
    portfolio = repository.load_portfolio()

    if not portfolio.positions:
        raise AssertionError("portfolio.json has no positions to test")

    first_ticker = portfolio.positions[0].ticker.strip().upper()
    print(f"Using data dir: {paths.root}")
    print(f"Testing auto news discovery for ticker: {first_ticker}")

    discovery = AutoNewsDiscovery(
        repository,
        finnhub_api_key=os.environ.get("FINNHUB_API_KEY"),
    )
    company_names = discovery.ensure_company_names([first_ticker])
    company_name = company_names.get(first_ticker, first_ticker)
    results = discovery.discover_for_ticker(first_ticker, company_name)

    if not results:
        raise AssertionError(
            f"No news discovered for {first_ticker}; "
            "check network access and portfolio ticker validity"
        )

    required_keys = {"ticker", "title", "url"}
    for item in results:
        missing = required_keys - set(item)
        if missing:
            raise AssertionError(f"discovered item missing keys {missing}: {item}")
        if item["ticker"] != first_ticker:
            raise AssertionError(f"unexpected ticker in result: {item}")
        if not item["title"].strip() or not item["url"].strip():
            raise AssertionError(f"empty title or url in result: {item}")

    print(f"Discovered {len(results)} article(s) for {first_ticker}")
    print("Sample:", results[0])
    print("Auto news discovery checks passed.")


if __name__ == "__main__":
    try:
        run_test()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
