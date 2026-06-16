"""LLM-backed pros/cons investment memos per portfolio ticker."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import httpx

from analysis.llm import LlmClient
from analysis.move_explainer import recent_news_titles_for_ticker
from collectors.market_data import portfolio_tickers
from storage.models import AppConfig, BotState, NewsCache, SignalsFile, TickerProsConsMemo
from storage.portfolio_ops import normalize_ticker
from storage.repository import DataRepository

logger = logging.getLogger(__name__)

MemoSource = Literal["llm", "fallback"]
HEADLINE_LIMIT = 5
_DEFAULT_SCORE = 0.0
_DEFAULT_PRICE_CHANGE = 0.0


@dataclass(frozen=True)
class ProsConsResult:
    """Generated pros/cons memo for one ticker."""

    ticker: str
    memo: str
    source: MemoSource
    generated_at: datetime


class ProsConsEngine:
    """Build and persist per-ticker pros/cons memos from cached signals."""

    def __init__(self, llm: LlmClient, app_config: AppConfig) -> None:
        self._llm = llm
        self._app_config = app_config

    def generate_for_ticker(
        self,
        ticker: str,
        *,
        repository: DataRepository,
    ) -> ProsConsResult:
        """Read cached inputs, call Ollama when enabled, and persist pros_cons."""
        symbol = normalize_ticker(ticker)
        signals = repository.load_signals()
        state = repository.load_state()
        news_cache = repository.load_news_cache()

        score, article_count = _sentiment_for_ticker(signals, symbol)
        price_change, company_name = _price_context_for_ticker(state, symbol, repository)
        headlines = recent_news_titles_for_ticker(
            news_cache,
            symbol,
            limit=HEADLINE_LIMIT,
        )

        if self._app_config.enable_llm_summaries and self._llm.is_configured:
            try:
                prompt = build_pros_cons_prompt(
                    symbol,
                    company_name=company_name,
                    score=score,
                    price_change=price_change,
                    article_count=article_count,
                    headlines=headlines,
                )
                memo = self._llm.generate(prompt)
                result = ProsConsResult(
                    ticker=symbol,
                    memo=memo.strip(),
                    source="llm",
                    generated_at=datetime.now(tz=UTC),
                )
            except (httpx.HTTPError, httpx.TimeoutException, ValueError) as exc:
                logger.warning("Pros/cons LLM failed for %s: %s", symbol, exc)
                result = _fallback_result(
                    symbol,
                    score=score,
                    price_change=price_change,
                )
        else:
            result = _fallback_result(
                symbol,
                score=score,
                price_change=price_change,
            )

        self._persist_result(repository, result)
        return result

    def _persist_result(self, repository: DataRepository, result: ProsConsResult) -> None:
        signals = repository.load_signals()
        signals.pros_cons[result.ticker] = TickerProsConsMemo(
            memo=result.memo,
            generated_at=result.generated_at,
            source=result.source,
        )
        repository.save_signals(signals)


def build_pros_cons_prompt(
    ticker: str,
    *,
    company_name: str,
    score: float,
    price_change: float,
    article_count: int,
    headlines: list[str],
) -> str:
    """Build the Ollama prompt for a single-ticker pros/cons memo."""
    label = company_name.strip() or ticker.strip().upper()
    if headlines:
        headlines_block = "\n".join(f"- {line}" for line in headlines)
    else:
        headlines_block = "- (none)"

    return (
        f"You are a portfolio analyst. Evaluate {ticker.strip().upper()} ({label}) "
        "for a retail investor.\n\n"
        "Signals:\n"
        f"- 24h sentiment score: {score:+.2f} "
        "(scale: -1.0 very bearish, +1.0 very bullish)\n"
        f"- 24h price change: {price_change:+.1f}%\n"
        f"- Recent headlines ({article_count} articles analysed):\n"
        f"{headlines_block}\n\n"
        "Write a concise investment memo in this exact format:\n"
        "PROS:\n"
        "- <bullet>\n"
        "- <bullet>\n\n"
        "CONS:\n"
        "- <bullet>\n"
        "- <bullet>\n\n"
        "SHORT-TERM OUTLOOK (1–5 days): <one sentence>\n\n"
        "Be specific. No financial advice disclaimer."
    )


def run_pros_cons_job(
    repository: DataRepository,
    llm: LlmClient,
    app_config: AppConfig,
    *,
    notifier=None,
) -> list[ProsConsResult]:
    """Generate memos for all portfolio tickers and alert on sentiment shifts."""
    portfolio = repository.load_portfolio()
    symbols = portfolio_tickers(portfolio)
    if not symbols:
        logger.info("Pros/cons job skipped: portfolio is empty")
        return []

    engine = ProsConsEngine(llm, app_config)
    signals_before = repository.load_signals()
    previous_scores = dict(signals_before.pros_cons_last_sentiment)
    current_scores = {
        symbol: record.score
        for symbol, record in signals_before.sentiment.items()
    }

    results: list[ProsConsResult] = []
    for symbol in symbols:
        results.append(engine.generate_for_ticker(symbol, repository=repository))

    shifts = sentiment_shifts(
        symbols,
        current_scores=current_scores,
        previous_scores=previous_scores,
        threshold=app_config.sentiment_alert_threshold,
    )
    if shifts and notifier is not None:
        _deliver_sentiment_shift_alerts(notifier, repository, shifts, results)

    signals_after = repository.load_signals()
    signals_after.pros_cons_last_sentiment = current_scores
    repository.save_signals(signals_after)

    logger.info(
        "Pros/cons job finished for %d ticker(s); %d sentiment shift alert(s)",
        len(results),
        len(shifts),
    )
    return results


def sentiment_shifts(
    tickers: list[str],
    *,
    current_scores: dict[str, float],
    previous_scores: dict[str, float],
    threshold: float,
) -> list[tuple[str, float, float]]:
    """Return tickers whose sentiment moved more than threshold since last run."""
    shifts: list[tuple[str, float, float]] = []
    for ticker in tickers:
        symbol = normalize_ticker(ticker)
        current = current_scores.get(symbol)
        previous = previous_scores.get(symbol)
        if current is None or previous is None:
            continue
        if abs(current - previous) > threshold:
            shifts.append((symbol, previous, current))
    return shifts


def _fallback_result(
    ticker: str,
    *,
    score: float,
    price_change: float,
) -> ProsConsResult:
    return ProsConsResult(
        ticker=ticker,
        memo=(
            f"Sentiment: {score:+.2f}. "
            f"Price: {price_change:+.1f}%. "
            "LLM unavailable."
        ),
        source="fallback",
        generated_at=datetime.now(tz=UTC),
    )


def _sentiment_for_ticker(signals: SignalsFile, ticker: str) -> tuple[float, int]:
    record = signals.sentiment.get(ticker)
    if record is None:
        return _DEFAULT_SCORE, 0
    return record.score, record.article_count


def _price_context_for_ticker(
    state: BotState,
    ticker: str,
    repository: DataRepository,
) -> tuple[float, str]:
    quote = state.latest_prices.get(ticker)
    price_change = _DEFAULT_PRICE_CHANGE
    company_name = ""
    if quote is not None:
        if quote.change_pct is not None:
            price_change = quote.change_pct
        company_name = quote.company_name.strip()

    if not company_name:
        metadata = repository.load_ticker_metadata()
        company_name = metadata.ticker_to_company_name.get(ticker, "")

    return price_change, company_name


def _deliver_sentiment_shift_alerts(
    notifier,
    repository: DataRepository,
    shifts: list[tuple[str, float, float]],
    results: list[ProsConsResult],
) -> None:
    if not notifier.is_configured:
        logger.warning("Telegram notifier not configured; skipping sentiment shift alerts")
        return

    memos_by_ticker = {result.ticker: result.memo for result in results}
    users = repository.load_users().users
    for symbol, previous, current in shifts:
        memo = memos_by_ticker.get(symbol, "")
        message = (
            f"Sentiment shift: {symbol}\n"
            f"Score moved from {previous:+.2f} to {current:+.2f}.\n\n"
            f"{memo}"
        )
        for user in users:
            try:
                from bot.formatter import truncate_message

                notifier.send_text(user.chat_id, truncate_message(message))
            except Exception:
                logger.exception(
                    "Failed to send sentiment shift alert for %s to chat_id=%s",
                    symbol,
                    user.chat_id,
                )
