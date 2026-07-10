"""Canonical portfolio cash balances: native buckets and HKD equivalents."""

from __future__ import annotations

from dataclasses import dataclass

from analysis.portfolio_valuation import (
    HKD,
    _DEFAULT_JPY_TO_HKD,
    _DEFAULT_USD_TO_HKD,
)
from storage.models import Portfolio


@dataclass(frozen=True)
class CashBucket:
    """One native cash currency bucket with HKD equivalent."""

    currency: str
    native_amount: float
    hkd_equivalent: float
    fx_rate_to_hkd: float


@dataclass(frozen=True)
class PortfolioCashBalances:
    """All cash buckets for a portfolio with FX conversion metadata."""

    buckets: tuple[CashBucket, ...]
    total_hkd: float
    usd_to_hkd: float
    jpy_to_hkd: float

    def bucket(self, currency: str) -> CashBucket | None:
        """Return a bucket by currency code, if present."""
        code = currency.strip().upper()
        for item in self.buckets:
            if item.currency == code:
                return item
        return None


def _native_amounts(portfolio: Portfolio) -> list[tuple[str, float]]:
    rows: list[tuple[str, float]] = []
    if portfolio.cash > 0:
        rows.append((HKD, portfolio.cash))
    if portfolio.cash_usd > 0:
        rows.append(("USD", portfolio.cash_usd))
    if portfolio.cash_jpy > 0:
        rows.append(("JPY", portfolio.cash_jpy))
    return rows


def build_portfolio_cash_balances(
    portfolio: Portfolio,
    *,
    fx_rates: dict[str, float] | None = None,
) -> PortfolioCashBalances:
    """Build native cash buckets with HKD equivalents using live or cached FX."""
    from analysis.portfolio_valuation import fetch_fx_rates_to_hkd

    natives = _native_amounts(portfolio)
    if not natives:
        return PortfolioCashBalances(
            buckets=(),
            total_hkd=0.0,
            usd_to_hkd=_DEFAULT_USD_TO_HKD,
            jpy_to_hkd=_DEFAULT_JPY_TO_HKD,
        )

    rates = dict(fx_rates or {})
    if "USD" not in rates:
        rates.update(fetch_fx_rates_to_hkd({"USD", "JPY"}))
    usd_rate = rates.get("USD", _DEFAULT_USD_TO_HKD)
    jpy_rate = rates.get("JPY", _DEFAULT_JPY_TO_HKD)

    buckets: list[CashBucket] = []
    total_hkd = 0.0
    for currency, native in natives:
        if currency == HKD:
            rate = 1.0
            hkd = native
        elif currency == "USD":
            rate = usd_rate
            hkd = native * rate
        elif currency == "JPY":
            rate = jpy_rate
            hkd = native * rate
        else:
            rate = rates.get(currency, 1.0)
            hkd = native * rate
        buckets.append(
            CashBucket(
                currency=currency,
                native_amount=native,
                hkd_equivalent=hkd,
                fx_rate_to_hkd=rate,
            )
        )
        total_hkd += hkd

    return PortfolioCashBalances(
        buckets=tuple(buckets),
        total_hkd=total_hkd,
        usd_to_hkd=usd_rate,
        jpy_to_hkd=jpy_rate,
    )


def portfolio_cash_total_hkd(
    portfolio: Portfolio,
    *,
    usd_to_hkd: float | None = None,
    jpy_to_hkd: float | None = None,
) -> float:
    """Return total cash in HKD using the canonical cash balance model."""
    fx_rates: dict[str, float] = {HKD: 1.0}
    if usd_to_hkd is not None:
        fx_rates["USD"] = usd_to_hkd
    if jpy_to_hkd is not None:
        fx_rates["JPY"] = jpy_to_hkd
    return build_portfolio_cash_balances(portfolio, fx_rates=fx_rates or None).total_hkd


def _format_native_amount(currency: str, amount: float) -> str:
    if currency == "JPY":
        return f"{amount:,.0f}"
    return f"{amount:,.2f}"


def format_cash_balance_lines(
    balances: PortfolioCashBalances,
    *,
    lang: str = "en",
    include_fx_note: bool = True,
    include_bookkeeping_note: bool = False,
) -> list[str]:
    """Format explicit native + HKD-equivalent cash lines for Telegram."""
    from bot.i18n import t

    if balances.total_hkd <= 0 and not balances.buckets:
        return [t("cash_empty", lang)]

    lines = [t("cash_header_total", lang, total_hkd=balances.total_hkd)]
    if include_fx_note and (
        balances.bucket("USD") is not None or balances.bucket("JPY") is not None
    ):
        lines.append(
            t(
                "cash_fx_note",
                lang,
                usd_rate=balances.usd_to_hkd,
                jpy_rate=balances.jpy_to_hkd,
            )
        )

    for bucket in balances.buckets:
        native = _format_native_amount(bucket.currency, bucket.native_amount)
        if bucket.currency == HKD:
            lines.append(
                t(
                    "cash_bucket_hkd",
                    lang,
                    native=native,
                    hkd=bucket.hkd_equivalent,
                )
            )
        else:
            lines.append(
                t(
                    "cash_bucket_fx",
                    lang,
                    currency=bucket.currency,
                    native=native,
                    hkd=bucket.hkd_equivalent,
                    rate=bucket.fx_rate_to_hkd,
                )
            )

    if include_bookkeeping_note:
        lines.append(t("cash_bookkeeping_note", lang))
    return lines


def format_cash_balance_text(
    portfolio: Portfolio,
    *,
    lang: str = "en",
    fx_rates: dict[str, float] | None = None,
    include_fx_note: bool = True,
    include_bookkeeping_note: bool = False,
    detailed: bool = True,
) -> str:
    """Return a cash summary for messages; detailed=False shows HKD total only."""
    from bot.i18n import t

    balances = build_portfolio_cash_balances(portfolio, fx_rates=fx_rates)
    if not detailed:
        return t("cash_simple_total", lang, total_hkd=balances.total_hkd)
    return "\n".join(
        format_cash_balance_lines(
            balances,
            lang=lang,
            include_fx_note=include_fx_note,
            include_bookkeeping_note=include_bookkeeping_note,
        )
    )


def append_portfolio_cash_lines(
    lines: list[str],
    portfolio: Portfolio,
    *,
    lang: str = "en",
    usd_to_hkd: float | None = None,
    detailed: bool = False,
    include_bookkeeping_note: bool = False,
) -> None:
    """Append portfolio cash lines using detailed or legacy formatting."""
    from bot.i18n import t

    cash_hkd = portfolio_cash_total_hkd(portfolio, usd_to_hkd=usd_to_hkd)
    if cash_hkd <= 0:
        return

    if detailed:
        fx_rates: dict[str, float] | None = None
        if usd_to_hkd is not None:
            fx_rates = {"USD": usd_to_hkd}
        balances = build_portfolio_cash_balances(portfolio, fx_rates=fx_rates)
        lines.extend(
            format_cash_balance_lines(
                balances,
                lang=lang,
                include_bookkeeping_note=include_bookkeeping_note,
            )
        )
        return

    cash_parts: list[str] = []
    if portfolio.cash > 0:
        cash_parts.append(f"{portfolio.cash:,.2f} HKD")
    if portfolio.cash_usd > 0:
        cash_parts.append(f"{portfolio.cash_usd:,.2f} USD")
    if portfolio.cash_jpy > 0:
        cash_parts.append(f"{portfolio.cash_jpy:,.0f} JPY")
    if len(cash_parts) > 1 or portfolio.cash_usd > 0 or portfolio.cash_jpy > 0:
        lines.append(
            t(
                "portfolio_cash_multi",
                lang,
                breakdown=" + ".join(cash_parts),
                total_hkd=cash_hkd,
            )
        )
    else:
        lines.append(t("portfolio_cash", lang, cash=portfolio.cash))
