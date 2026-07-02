"""Portfolio ticker validation and mutation helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass

from storage.models import BotState, Portfolio, Position, PositionLot

_TICKER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,14}$")


@dataclass(frozen=True)
class PortfolioTickerResult:
    """Outcome of adding or removing a portfolio ticker."""

    success: bool
    message: str
    ticker: str = ""
    is_new_position: bool = False


@dataclass(frozen=True)
class SellTickerResult:
    """Outcome of selling shares from a portfolio position."""

    success: bool
    message: str
    ticker: str = ""
    shares_sold: float = 0.0
    sell_price: float = 0.0
    proceeds: float = 0.0
    proceeds_currency: str = "HKD"
    proceeds_hkd: float = 0.0
    cash_balance: float = 0.0
    cash_balance_hkd: float = 0.0
    fully_sold: bool = False


def normalize_ticker(symbol: str) -> str:
    """Normalize a ticker symbol for storage and lookup."""
    return symbol.strip().upper()


def _portfolio_tickers(portfolio: Portfolio) -> list[str]:
    seen: set[str] = set()
    tickers: list[str] = []
    for position in portfolio.positions:
        symbol = normalize_ticker(position.ticker)
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        tickers.append(symbol)
    return tickers


def validate_ticker_format(symbol: str) -> str | None:
    """Return an error message when the symbol format is invalid."""
    normalized = normalize_ticker(symbol)
    if not normalized:
        return "Ticker symbol is empty."
    if not _TICKER_PATTERN.fullmatch(normalized):
        return (
            f"Invalid ticker format: {normalized!r}. "
            "Use letters, digits, dots, or hyphens (e.g. AAPL, 1810.HK)."
        )
    return None


def verify_ticker_exists(symbol: str) -> str | None:
    """Return an error message when yfinance cannot resolve the ticker."""
    from collectors.market_data import fetch_quote

    try:
        fetch_quote(symbol)
    except Exception as exc:
        return f"Unknown or unavailable ticker: {symbol} ({exc})"
    return None


def portfolio_has_ticker(portfolio: Portfolio, symbol: str) -> bool:
    """Return True when the portfolio already holds the normalized ticker."""
    return normalize_ticker(symbol) in _portfolio_tickers(portfolio)


def _portfolio_has_ticker(portfolio: Portfolio, symbol: str) -> bool:
    return portfolio_has_ticker(portfolio, symbol)


def _reduce_lots_fifo(
    lots: list[PositionLot],
    shares_to_sell: float,
) -> list[PositionLot]:
    """Consume shares from oldest lots first (FIFO)."""
    remaining = shares_to_sell
    updated: list[PositionLot] = []
    for lot in lots:
        if remaining <= 1e-9:
            updated.append(lot)
            continue
        if lot.shares <= remaining + 1e-9:
            remaining -= lot.shares
            continue
        updated.append(lot.model_copy(update={"shares": lot.shares - remaining}))
        remaining = 0.0
    if remaining > 1e-9:
        raise ValueError("cannot sell more shares than held in lots")
    return updated


def _new_lot(
    shares: float,
    cost: float | None,
    *,
    lot_date: str | None = None,
) -> PositionLot:
    """Build a purchase lot for /add_ticker."""
    from datetime import UTC, datetime

    purchased_on = lot_date or datetime.now(tz=UTC).date().isoformat()
    return PositionLot(shares=shares, cost=cost, date=purchased_on)


def add_ticker_to_portfolio(
    portfolio: Portfolio,
    symbol: str,
    *,
    shares: float = 1.0,
    cost_basis: float | None = None,
) -> tuple[Portfolio, PortfolioTickerResult]:
    """Add shares for a ticker, creating a new position or increasing an existing one."""
    normalized = normalize_ticker(symbol)
    format_error = validate_ticker_format(normalized)
    if format_error:
        return portfolio, PortfolioTickerResult(False, format_error, normalized)

    if shares <= 0:
        return portfolio, PortfolioTickerResult(
            False,
            "Shares must be greater than zero.",
            normalized,
        )

    if cost_basis is not None and cost_basis <= 0:
        return portfolio, PortfolioTickerResult(
            False,
            "Cost basis must be greater than zero.",
            normalized,
        )

    if _portfolio_has_ticker(portfolio, normalized):
        new_positions: list[Position] = []
        updated = False
        new_total = 0.0
        blended_cost: float | None = None
        for position in portfolio.positions:
            if normalize_ticker(position.ticker) == normalized:
                new_lots = [*position.lots, _new_lot(shares, cost_basis)]
                updated_position = position.model_copy(update={"lots": new_lots})
                new_total = updated_position.shares
                blended_cost = updated_position.blended_cost_basis
                new_positions.append(updated_position)
                updated = True
            else:
                new_positions.append(position)
        if not updated:
            return portfolio, PortfolioTickerResult(
                False,
                f"{normalized} is not in the portfolio.",
                normalized,
            )
        updated_portfolio = portfolio.model_copy(update={"positions": new_positions})
        cost_note = (
            f"; blended cost {blended_cost:g}"
            if blended_cost is not None
            else ""
        )
        return updated_portfolio, PortfolioTickerResult(
            True,
            (
                f"Added lot of {shares:g} share(s) to {normalized}; "
                f"now holding {new_total:g} share(s) in {len(updated_position.lots)} lot(s){cost_note}."
            ),
            normalized,
            is_new_position=False,
        )

    new_position = Position(
        ticker=normalized,
        lots=[_new_lot(shares, cost_basis)],
    )
    updated = portfolio.model_copy(
        update={
            "positions": [
                *portfolio.positions,
                new_position,
            ]
        }
    )
    cost_note = f" at cost {cost_basis:g}" if cost_basis is not None else ""
    return updated, PortfolioTickerResult(
        True,
        f"Added {normalized} ({shares:g} share(s){cost_note}) to the portfolio.",
        normalized,
        is_new_position=True,
    )


def remove_ticker_from_portfolio(
    portfolio: Portfolio,
    symbol: str,
) -> tuple[Portfolio, PortfolioTickerResult]:
    """Return an updated portfolio without the ticker, or an error result."""
    normalized = normalize_ticker(symbol)
    format_error = validate_ticker_format(normalized)
    if format_error:
        return portfolio, PortfolioTickerResult(False, format_error, normalized)

    if not _portfolio_has_ticker(portfolio, normalized):
        return portfolio, PortfolioTickerResult(
            False,
            f"{normalized} is not in the portfolio.",
            normalized,
        )

    updated = portfolio.model_copy(
        update={
            "positions": [
                position
                for position in portfolio.positions
                if normalize_ticker(position.ticker) != normalized
            ]
        }
    )
    return updated, PortfolioTickerResult(
        True,
        f"Removed {normalized} from the portfolio.",
        normalized,
    )


@dataclass(frozen=True)
class CashDepositResult:
    """Result of crediting cash to the portfolio."""

    success: bool
    message: str
    amount: float = 0.0
    currency: str = "HKD"
    cash_balance: float = 0.0
    cash_balance_hkd: float = 0.0


def deposit_cash_to_portfolio(
    portfolio: Portfolio,
    amount: float,
    *,
    currency: str = "HKD",
) -> tuple[Portfolio, CashDepositResult]:
    """Credit cash to the portfolio balance in HKD, USD, or JPY."""
    from analysis.portfolio_valuation import portfolio_cash_hkd

    if amount <= 0:
        return portfolio, CashDepositResult(
            False,
            "Deposit amount must be greater than zero.",
            amount,
            currency,
            portfolio.cash,
            portfolio_cash_hkd(portfolio),
        )

    code = currency.strip().upper() or "HKD"
    if code not in ("HKD", "USD", "JPY"):
        return portfolio, CashDepositResult(
            False,
            f"Unsupported deposit currency {code}; use HKD, USD, or JPY.",
            amount,
            code,
            portfolio.cash,
            portfolio_cash_hkd(portfolio),
        )

    if code == "USD":
        new_cash_usd = portfolio.cash_usd + amount
        updated = portfolio.model_copy(update={"cash_usd": new_cash_usd})
        balance_hkd = portfolio_cash_hkd(updated)
        return updated, CashDepositResult(
            True,
            (
                f"Deposited {amount:g} USD; "
                f"USD cash {new_cash_usd:,.2f} (≈ {balance_hkd:,.2f} HKD total cash)."
            ),
            amount,
            code,
            new_cash_usd,
            balance_hkd,
        )

    if code == "JPY":
        new_cash_jpy = portfolio.cash_jpy + amount
        updated = portfolio.model_copy(update={"cash_jpy": new_cash_jpy})
        balance_hkd = portfolio_cash_hkd(updated)
        return updated, CashDepositResult(
            True,
            (
                f"Deposited {amount:g} JPY; "
                f"JPY cash {new_cash_jpy:,.0f} (≈ {balance_hkd:,.2f} HKD total cash)."
            ),
            amount,
            code,
            new_cash_jpy,
            balance_hkd,
        )

    new_cash = portfolio.cash + amount
    updated = portfolio.model_copy(update={"cash": new_cash})
    balance_hkd = portfolio_cash_hkd(updated)
    return updated, CashDepositResult(
        True,
        f"Deposited {amount:g} HKD; cash balance {new_cash:,.2f} HKD (≈ {balance_hkd:,.2f} HKD total).",
        amount,
        code,
        new_cash,
        balance_hkd,
    )


def sell_ticker_from_portfolio(
    portfolio: Portfolio,
    symbol: str,
    *,
    sell_price: float,
    shares: float | None = None,
    state: BotState | None = None,
) -> tuple[Portfolio, SellTickerResult]:
    """Sell shares at a given price, remove or reduce the position, and credit HKD cash."""
    from analysis.portfolio_valuation import (
        convert_to_hkd,
        fetch_fx_rates_to_hkd,
        infer_quote_currency,
        portfolio_cash_hkd,
    )

    normalized = normalize_ticker(symbol)
    format_error = validate_ticker_format(normalized)
    if format_error:
        return portfolio, SellTickerResult(False, format_error, normalized)

    if sell_price <= 0:
        return portfolio, SellTickerResult(
            False,
            "Sell price must be greater than zero.",
            normalized,
        )

    position = next(
        (
            item
            for item in portfolio.positions
            if normalize_ticker(item.ticker) == normalized
        ),
        None,
    )
    if position is None:
        return portfolio, SellTickerResult(
            False,
            f"{normalized} is not in the portfolio.",
            normalized,
        )

    shares_to_sell = position.shares if shares is None else shares
    if shares_to_sell <= 0:
        return portfolio, SellTickerResult(
            False,
            "Shares to sell must be greater than zero.",
            normalized,
        )
    if shares_to_sell > position.shares + 1e-9:
        return portfolio, SellTickerResult(
            False,
            (
                f"Cannot sell {shares_to_sell:g} share(s) of {normalized}; "
                f"only {position.shares:g} held."
            ),
            normalized,
        )

    proceeds_native = shares_to_sell * sell_price
    quote = state.latest_prices.get(normalized) if state is not None else None
    currency = infer_quote_currency(quote, normalized)
    fx_rates = fetch_fx_rates_to_hkd({currency})
    proceeds_hkd = convert_to_hkd(proceeds_native, currency, fx_rates=fx_rates)
    new_cash = portfolio.cash + proceeds_hkd
    fully_sold = abs(shares_to_sell - position.shares) < 1e-9

    if fully_sold:
        new_positions = [
            item
            for item in portfolio.positions
            if normalize_ticker(item.ticker) != normalized
        ]
    else:
        remaining_lots = _reduce_lots_fifo(position.lots, shares_to_sell)
        new_positions = [
            (
                item.model_copy(update={"lots": remaining_lots})
                if normalize_ticker(item.ticker) == normalized
                else item
            )
            for item in portfolio.positions
        ]

    updated = portfolio.model_copy(
        update={"positions": new_positions, "cash": new_cash}
    )
    action = "Sold all" if fully_sold else f"Sold {shares_to_sell:g}"
    if currency in ("HKD", "HK"):
        proceeds_note = f"proceeds {proceeds_native:,.2f} HKD"
    else:
        proceeds_note = (
            f"proceeds {proceeds_native:,.2f} {currency} "
            f"(≈ {proceeds_hkd:,.2f} HKD credited)"
        )
    balance_hkd = portfolio_cash_hkd(updated, usd_to_hkd=fx_rates.get("USD"))
    message = (
        f"{action} share(s) of {normalized} at {sell_price:g}; "
        f"{proceeds_note} (cash balance ≈ {balance_hkd:,.2f} HKD)."
    )
    return updated, SellTickerResult(
        True,
        message,
        normalized,
        shares_sold=shares_to_sell,
        sell_price=sell_price,
        proceeds=proceeds_native,
        proceeds_currency=currency,
        proceeds_hkd=proceeds_hkd,
        cash_balance=new_cash,
        cash_balance_hkd=balance_hkd,
        fully_sold=fully_sold,
    )
