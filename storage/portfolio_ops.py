"""Portfolio ticker validation and mutation helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass

from storage.models import Portfolio, Position

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
    cash_balance: float = 0.0
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


def add_ticker_to_portfolio(
    portfolio: Portfolio,
    symbol: str,
    *,
    shares: float = 1.0,
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

    if _portfolio_has_ticker(portfolio, normalized):
        new_positions: list[Position] = []
        updated = False
        new_total = 0.0
        for position in portfolio.positions:
            if normalize_ticker(position.ticker) == normalized:
                new_total = position.shares + shares
                new_positions.append(
                    position.model_copy(update={"shares": new_total})
                )
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
        return updated_portfolio, PortfolioTickerResult(
            True,
            (
                f"Added {shares:g} share(s) to {normalized}; "
                f"now holding {new_total:g} share(s)."
            ),
            normalized,
            is_new_position=False,
        )

    updated = portfolio.model_copy(
        update={
            "positions": [
                *portfolio.positions,
                Position(ticker=normalized, shares=shares),
            ]
        }
    )
    return updated, PortfolioTickerResult(
        True,
        f"Added {normalized} ({shares:g} share(s)) to the portfolio.",
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


def sell_ticker_from_portfolio(
    portfolio: Portfolio,
    symbol: str,
    *,
    sell_price: float,
    shares: float | None = None,
) -> tuple[Portfolio, SellTickerResult]:
    """Sell shares at a given price, remove or reduce the position, and credit cash."""
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

    proceeds = shares_to_sell * sell_price
    new_cash = portfolio.cash + proceeds
    fully_sold = abs(shares_to_sell - position.shares) < 1e-9

    if fully_sold:
        new_positions = [
            item
            for item in portfolio.positions
            if normalize_ticker(item.ticker) != normalized
        ]
    else:
        remaining = position.shares - shares_to_sell
        new_positions = [
            (
                item.model_copy(update={"shares": remaining})
                if normalize_ticker(item.ticker) == normalized
                else item
            )
            for item in portfolio.positions
        ]

    updated = portfolio.model_copy(
        update={"positions": new_positions, "cash": new_cash}
    )
    action = "Sold all" if fully_sold else f"Sold {shares_to_sell:g}"
    message = (
        f"{action} share(s) of {normalized} at {sell_price:g}; "
        f"proceeds {proceeds:,.2f} (cash balance {new_cash:,.2f})."
    )
    return updated, SellTickerResult(
        True,
        message,
        normalized,
        shares_sold=shares_to_sell,
        sell_price=sell_price,
        proceeds=proceeds,
        cash_balance=new_cash,
        fully_sold=fully_sold,
    )
