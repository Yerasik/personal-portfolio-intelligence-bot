"""Parsing helpers for /deposit_cash command arguments."""

from __future__ import annotations

from dataclasses import dataclass

_SUPPORTED_CURRENCIES = frozenset({"HKD", "USD", "JPY"})


@dataclass(frozen=True)
class DepositCashParseResult:
    """Validated /deposit_cash arguments."""

    amount: float
    currency: str
    note: str | None


def parse_deposit_cash_args(args: list[str]) -> tuple[DepositCashParseResult | None, str | None]:
    """Parse /deposit_cash <amount> [HKD|USD|JPY] [note]."""
    if not args:
        return None, "deposit_cash_usage"

    try:
        amount = float(args[0])
    except ValueError:
        return None, "deposit_cash_amount_invalid"

    if amount <= 0:
        return None, "deposit_cash_amount_invalid"

    currency = "HKD"
    note_parts = args[1:]
    if note_parts and note_parts[0].strip().upper() in _SUPPORTED_CURRENCIES:
        currency = note_parts[0].strip().upper()
        note_parts = note_parts[1:]

    note = " ".join(note_parts).strip() or None
    return DepositCashParseResult(amount=amount, currency=currency, note=note), None
