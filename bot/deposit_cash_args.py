"""Parsing helpers for /deposit_cash command arguments."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DepositCashParseResult:
    """Validated /deposit_cash arguments."""

    amount: float
    note: str | None


def parse_deposit_cash_args(args: list[str]) -> tuple[DepositCashParseResult | None, str | None]:
    """Parse /deposit_cash <amount> [note]."""
    if not args:
        return None, "deposit_cash_usage"

    try:
        amount = float(args[0])
    except ValueError:
        return None, "deposit_cash_amount_invalid"

    note = " ".join(args[1:]).strip() or None
    if len(args) > 1 and note is None:
        note = None

    if amount <= 0:
        return None, "deposit_cash_amount_invalid"

    return DepositCashParseResult(amount=amount, note=note), None
