#!/usr/bin/env python3
"""Notify ordinary users about stored strategies for all portfolio tickers.

Use this to backfill Telegram announcements when strategies were saved before
notifications were wired up, or after /edit_strategy without delivery.

Examples:
  docker compose run --rm --no-deps portfolio-bot \\
    python scripts/notify_portfolio_strategies.py --dry-run

  docker compose run --rm --no-deps portfolio-bot \\
    python scripts/notify_portfolio_strategies.py --save-translations

  docker compose run --rm --no-deps portfolio-bot \\
    python scripts/notify_portfolio_strategies.py --ticker VRT
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.llm import LlmClient
from bot.notifier import TelegramNotifier
from bot.strategy_broadcast import notify_portfolio_strategies
from config.settings import RuntimeSettings
from storage.paths import resolve_data_paths
from storage.portfolio_ops import normalize_ticker
from storage.repository import DataRepository


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Send stored investment strategies to ordinary Telegram users.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be sent without calling Telegram or saving translations.",
    )
    parser.add_argument(
        "--save-translations",
        action="store_true",
        help="Persist missing localized strategy text before notifying users.",
    )
    parser.add_argument(
        "--mode",
        choices=("summary", "announcement"),
        default="summary",
        help=(
            "summary: full strategy text per user language (default). "
            "announcement: short new-holding alert style message."
        ),
    )
    parser.add_argument(
        "--ticker",
        action="append",
        dest="tickers",
        metavar="SYMBOL",
        help="Limit to one or more tickers (repeat flag for multiple). Default: all holdings.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(levelname)s %(name)s: %(message)s",
    )

    settings = RuntimeSettings()
    paths = resolve_data_paths(settings.data_dir)
    repository = DataRepository(paths)
    app_config = repository.load_config()
    llm = LlmClient(settings=settings, app_config=app_config)
    notifier = TelegramNotifier(settings)

    if not args.dry_run and not notifier.is_configured:
        print("Telegram bot token is not configured.", file=sys.stderr)
        return 1

    tickers = [normalize_ticker(symbol) for symbol in args.tickers] if args.tickers else None
    report = notify_portfolio_strategies(
        repository,
        notifier,
        llm,
        app_config=app_config,
        tickers=tickers,
        mode=args.mode,
        save_translations=args.save_translations,
        dry_run=args.dry_run,
    )

    print(f"Ordinary users in users.json: {report.ordinary_user_count}")
    for result in report.results:
        if result.skipped:
            print(f"- {result.ticker}: skipped ({result.skip_reason})")
            continue
        action = "would notify" if args.dry_run else "notified"
        print(
            f"- {result.ticker}: {action} {result.users_notified} user(s)"
            + (
                f", saved {result.translations_saved} translation(s)"
                if result.translations_saved
                else ""
            )
        )

    if report.skipped_tickers:
        print(f"Skipped tickers: {', '.join(report.skipped_tickers)}")
    print(
        f"Total user deliveries: {report.notified_total}"
        + (" (dry run)" if args.dry_run else "")
    )

    if report.ordinary_user_count == 0:
        print("No ordinary users found — nothing to send.", file=sys.stderr)
        return 1
    if not report.results:
        print("No portfolio tickers matched.", file=sys.stderr)
        return 1
    if report.notified_total == 0 and not args.dry_run:
        print("No messages were delivered.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        raise
