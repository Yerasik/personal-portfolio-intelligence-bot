"""Deterministic portfolio valuation in Hong Kong dollars (no LLM)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from storage.models import BotState, MarketQuote, Portfolio, Position

logger = logging.getLogger(__name__)

HKD = "HKD"
_DEFAULT_USD_TO_HKD = 7.85
_FX_YAHOO_SYMBOLS = {
    "USD": "HKD=X",
    "CNY": "CNYHKD=X",
    "CNH": "CNYHKD=X",
}


@dataclass(frozen=True)
class PositionValuation:
    """HKD market value and P/L for one holding."""

    ticker: str
    shares: float
    currency: str
    price: float | None
    market_value_hkd: float | None
    cost_value_hkd: float | None
    pl_hkd: float | None
    pl_pct: float | None
    weight_pct: float | None


@dataclass(frozen=True)
class PortfolioValuation:
    """Aggregated portfolio figures converted to HKD."""

    positions: list[PositionValuation]
    total_market_value_hkd: float
    total_cost_value_hkd: float | None
    total_pl_hkd: float | None
    total_pl_pct: float | None
    usd_to_hkd: float


def infer_quote_currency(quote: MarketQuote | None, ticker: str) -> str:
    """Resolve the listing currency for a quote."""
    if quote is not None and quote.currency.strip():
        return quote.currency.strip().upper()
    symbol = ticker.strip().upper()
    if symbol.endswith(".HK"):
        return HKD
    return "USD"


def fetch_fx_rates_to_hkd(
    currencies: set[str],
    *,
    now: datetime | None = None,
) -> dict[str, float]:
    """Fetch FX rates to HKD via yfinance (USD/HKD, CNY/HKD, etc.)."""
    _ = now
    rates: dict[str, float] = {HKD: 1.0, "HK": 1.0}
    for currency in currencies:
        code = currency.strip().upper()
        if not code or code in rates:
            continue
        yahoo_symbol = _FX_YAHOO_SYMBOLS.get(code)
        if yahoo_symbol is None:
            logger.warning("No FX mapping for %s; using 1:1 to HKD", code)
            rates[code] = 1.0
            continue
        rates[code] = _fetch_yahoo_last_close(yahoo_symbol) or (
            _DEFAULT_USD_TO_HKD if code == "USD" else 1.0
        )
    return rates


def _fetch_yahoo_last_close(symbol: str) -> float | None:
    try:
        import yfinance as yf

        history = yf.Ticker(symbol).history(period="5d")
        if history is None or history.empty:
            return None
        return float(history["Close"].iloc[-1])
    except Exception as exc:
        logger.warning("FX fetch failed for %s: %s", symbol, exc)
        return None


def convert_to_hkd(
    amount: float,
    currency: str,
    *,
    fx_rates: dict[str, float],
) -> float:
    """Convert a monetary amount in listing currency to HKD."""
    code = currency.strip().upper() or HKD
    if code in (HKD, "HK"):
        return amount
    rate = fx_rates.get(code)
    if rate is None:
        rate = fx_rates.get("USD", _DEFAULT_USD_TO_HKD) if code == "USD" else 1.0
    return amount * rate


def value_position_hkd(
    position: Position,
    quote: MarketQuote | None,
    *,
    fx_rates: dict[str, float],
) -> PositionValuation:
    """Compute HKD value and unrealized P/L for one holding."""
    symbol = position.ticker.strip().upper()
    currency = infer_quote_currency(quote, symbol)
    price = quote.price if quote is not None else None

    market_value_hkd: float | None = None
    if price is not None:
        market_value_hkd = convert_to_hkd(
            price * position.shares,
            currency,
            fx_rates=fx_rates,
        )

    cost_value_hkd: float | None = None
    pl_hkd: float | None = None
    pl_pct: float | None = None
    if position.cost_basis is not None:
        cost_value_hkd = convert_to_hkd(
            position.cost_basis * position.shares,
            currency,
            fx_rates=fx_rates,
        )
        if market_value_hkd is not None:
            pl_hkd = market_value_hkd - cost_value_hkd
            if cost_value_hkd > 0:
                pl_pct = (pl_hkd / cost_value_hkd) * 100.0

    return PositionValuation(
        ticker=symbol,
        shares=position.shares,
        currency=currency,
        price=price,
        market_value_hkd=market_value_hkd,
        cost_value_hkd=cost_value_hkd,
        pl_hkd=pl_hkd,
        pl_pct=pl_pct,
        weight_pct=None,
    )


def build_portfolio_valuation(
    portfolio: Portfolio,
    state: BotState,
    *,
    fx_rates: dict[str, float] | None = None,
) -> PortfolioValuation:
    """Value all holdings in HKD and compute weights and total P/L."""
    currencies: set[str] = set()
    for position in portfolio.positions:
        symbol = position.ticker.strip().upper()
        quote = state.latest_prices.get(symbol)
        currencies.add(infer_quote_currency(quote, symbol))

    resolved_fx = dict(fx_rates or {})
    resolved_fx.setdefault(HKD, 1.0)
    missing = {code for code in currencies if code not in resolved_fx and code not in (HKD, "HK")}
    if missing:
        resolved_fx.update(fetch_fx_rates_to_hkd(missing))

    positions = [
        value_position_hkd(
            position,
            state.latest_prices.get(position.ticker.strip().upper()),
            fx_rates=resolved_fx,
        )
        for position in portfolio.positions
    ]

    total_market = sum(
        item.market_value_hkd for item in positions if item.market_value_hkd is not None
    )
    cost_parts = [
        item.cost_value_hkd for item in positions if item.cost_value_hkd is not None
    ]
    total_cost = sum(cost_parts) if len(cost_parts) == len(positions) and positions else None

    weighted_positions: list[PositionValuation] = []
    for item in positions:
        weight = None
        if item.market_value_hkd is not None and total_market > 0:
            weight = (item.market_value_hkd / total_market) * 100.0
        weighted_positions.append(
            PositionValuation(
                ticker=item.ticker,
                shares=item.shares,
                currency=item.currency,
                price=item.price,
                market_value_hkd=item.market_value_hkd,
                cost_value_hkd=item.cost_value_hkd,
                pl_hkd=item.pl_hkd,
                pl_pct=item.pl_pct,
                weight_pct=weight,
            )
        )

    total_pl_hkd: float | None = None
    total_pl_pct: float | None = None
    if total_cost is not None and total_cost > 0:
        total_pl_hkd = total_market - total_cost
        total_pl_pct = (total_pl_hkd / total_cost) * 100.0

    usd_to_hkd = resolved_fx.get("USD", _DEFAULT_USD_TO_HKD)
    return PortfolioValuation(
        positions=weighted_positions,
        total_market_value_hkd=total_market,
        total_cost_value_hkd=total_cost,
        total_pl_hkd=total_pl_hkd,
        total_pl_pct=total_pl_pct,
        usd_to_hkd=usd_to_hkd,
    )


def valuation_for_ticker(
    portfolio: Portfolio,
    state: BotState,
    ticker: str,
    *,
    fx_rates: dict[str, float] | None = None,
) -> PositionValuation | None:
    """Return HKD valuation for one portfolio ticker, if held."""
    symbol = ticker.strip().upper()
    position = next(
        (
            item
            for item in portfolio.positions
            if item.ticker.strip().upper() == symbol
        ),
        None,
    )
    if position is None:
        return None

    valuation = build_portfolio_valuation(portfolio, state, fx_rates=fx_rates)
    return next((item for item in valuation.positions if item.ticker == symbol), None)
