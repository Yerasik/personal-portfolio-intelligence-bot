#!/usr/bin/env python3
"""One-shot repair of performance_history.json totals from position values."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.portfolio_valuation import build_portfolio_valuation, portfolio_cash_hkd
from storage.paths import resolve_data_paths
from storage.performance_ops import repair_performance_history
from storage.repository import DataRepository


def main() -> int:
    data_dir = os.environ.get("DATA_DIR", ROOT / "data")
    paths = resolve_data_paths(data_dir)
    repo = DataRepository(paths)
    portfolio = repo.load_portfolio()
    state = repo.load_state()
    history = repo.load_performance_history()
    valuation = build_portfolio_valuation(portfolio, state)
    cash_hkd = portfolio_cash_hkd(
        portfolio,
        usd_to_hkd=valuation.usd_to_hkd,
        jpy_to_hkd=valuation.jpy_to_hkd,
    )
    repaired = repair_performance_history(history, latest_cash_hkd=cash_hkd)
    if repaired is history:
        print("Performance history already consistent; no changes written.")
        return 0

    repo.save_performance_history(repaired)
    print(
        f"Repaired {len(repaired.snapshots)} snapshot(s); "
        f"latest total_value={repaired.snapshots[-1].total_value:,.2f} HKD"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
