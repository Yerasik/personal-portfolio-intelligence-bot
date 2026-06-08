"""Startup validation for container and local runs.

Runs before Telegram polling starts. Fatal errors (bad Telegram creds, invalid
JSON) stop the process; Ollama probe failures are warnings only.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field

import httpx
from pydantic import ValidationError

from config.loader import ConfigurationBundle
from config.ollama import resolve_ollama_settings
from config.settings import RuntimeSettings
from storage.json_store import JsonStorageError, JsonStore
from storage.models import AppConfig, BotState, NewsCache, Portfolio, TickerIndustryMap
from storage.repository import DataRepository

logger = logging.getLogger(__name__)

_PLACEHOLDER_TOKENS = frozenset(
    {
        "",
        "your_bot_token_here",
        "changeme",
        "replace_me",
    }
)
_PLACEHOLDER_CHAT_IDS = frozenset(
    {
        "",
        "your_chat_id_here",
        "changeme",
        "replace_me",
    }
)
_OLLAMA_PROBE_TIMEOUT_SECONDS = 5.0


class StartupError(Exception):
    """Raised when mandatory startup checks fail."""


@dataclass(frozen=True)
class JsonDocumentStatus:
    """Result of validating one JSON persistence file."""

    name: str
    path: str
    existed_before_load: bool
    valid: bool = True


@dataclass
class StartupReport:
    """Summary of startup validation results."""

    json_documents: list[JsonDocumentStatus] = field(default_factory=list)
    ollama_reachable: bool | None = None
    ollama_message: str = ""


def _fatal(message: str) -> None:
    """Print a startup error to stderr before exiting the process."""
    print(f"FATAL: {message}", file=sys.stderr)


def load_runtime_settings() -> RuntimeSettings:
    """Load env settings and translate validation failures into clear fatal errors."""
    try:
        return RuntimeSettings()
    except ValidationError as exc:
        missing = []
        for error in exc.errors():
            loc = error.get("loc", ())
            if loc:
                field_name = str(loc[-1]).upper()
                missing.append(field_name)
        if missing:
            _fatal(
                "Missing required environment variable(s): "
                + ", ".join(sorted(set(missing)))
            )
        else:
            _fatal(f"Invalid environment configuration: {exc}")
        raise StartupError("Invalid runtime settings") from exc


def validate_telegram_credentials(runtime: RuntimeSettings) -> None:
    """Fail loudly when Telegram credentials are missing or still placeholders."""
    token = runtime.telegram_bot_token.strip()
    chat_id = str(runtime.telegram_chat_id).strip()

    if token.lower() in _PLACEHOLDER_TOKENS:
        _fatal(
            "TELEGRAM_BOT_TOKEN is missing or still set to a placeholder. "
            "Copy .env.example to .env and set a real bot token from @BotFather."
        )
        raise StartupError("Invalid TELEGRAM_BOT_TOKEN")

    if chat_id.lower() in _PLACEHOLDER_CHAT_IDS:
        _fatal(
            "TELEGRAM_CHAT_ID is missing or still set to a placeholder. "
            "Set TELEGRAM_CHAT_ID to your personal Telegram chat id."
        )
        raise StartupError("Invalid TELEGRAM_CHAT_ID")


def validate_json_documents(repository: DataRepository) -> StartupReport:
    """Load and validate JSON documents under the configured data directory."""
    store = JsonStore()
    paths = repository.paths
    documents = (
        ("config", paths.config, AppConfig),
        ("portfolio", paths.portfolio, Portfolio),
        ("ticker_industries", paths.ticker_industries, TickerIndustryMap),
        ("state", paths.state, BotState),
        ("news_cache", paths.news_cache, NewsCache),
    )

    report = StartupReport()
    for name, path, model_type in documents:
        existed = path.exists()
        try:
            store.read_model(path, model_type)
        except JsonStorageError as exc:
            _fatal(f"Invalid {name} JSON at {path}: {exc}")
            raise StartupError(f"Invalid JSON document: {name}") from exc

        status = JsonDocumentStatus(
            name=name,
            path=str(path),
            existed_before_load=existed,
        )
        report.json_documents.append(status)
        if existed:
            logger.info("Validated JSON document: %s (%s)", name, path)
        else:
            logger.warning(
                "Initialized missing JSON document with defaults: %s (%s)",
                name,
                path,
            )

    return report


def probe_ollama(configuration: ConfigurationBundle) -> StartupReport:
    """Check Ollama reachability when LLM summaries are enabled; warn only."""
    app_config = configuration.app_config
    runtime = configuration.runtime
    base_url, model = resolve_ollama_settings(runtime, app_config)
    report = StartupReport()

    if not app_config.enable_llm_summaries:
        report.ollama_reachable = None
        report.ollama_message = "LLM summaries disabled; Ollama availability not required"
        logger.info(report.ollama_message)
        return report

    tags_url = f"{base_url}/api/tags"
    try:
        with httpx.Client(timeout=_OLLAMA_PROBE_TIMEOUT_SECONDS) as client:
            response = client.get(tags_url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        report.ollama_reachable = False
        report.ollama_message = (
            f"Ollama is not reachable at {base_url} ({exc}). "
            "The bot will continue and use fallback summaries."
        )
        logger.warning(report.ollama_message)
        return report

    report.ollama_reachable = True
    report.ollama_message = f"Ollama reachable at {base_url} (model={model})"
    logger.info(report.ollama_message)
    return report


def log_startup_summary(configuration: ConfigurationBundle, report: StartupReport) -> None:
    """Emit a health-conscious startup summary for operators."""
    runtime = configuration.runtime
    app_config = configuration.app_config
    portfolio = configuration.portfolio
    state = configuration.state
    news_cache = configuration.news_cache
    ollama_base_url, ollama_model = resolve_ollama_settings(runtime, app_config)

    logger.info("Portfolio intelligence bot starting")
    logger.info("Process model: single Python process with background scheduler thread")
    logger.info("Data directory: %s", configuration.paths.root)
    logger.info("Log directory: %s", runtime.log_dir)
    logger.info("Timezone: %s", app_config.timezone)
    logger.info("Telegram chat id: %s", runtime.telegram_chat_id)
    logger.info("Portfolio positions: %d", len(portfolio.positions))
    logger.info("Focus industries: %d", len(app_config.focus_industries))
    logger.info("RSS feeds configured: %d", len(app_config.rss_feed_urls))
    logger.info("Cached news items: %d", len(news_cache.items))
    logger.info("Pending alerts: %d", len(state.pending_alerts))
    logger.info(
        "Scheduler intervals (minutes): market=%d news=%d rules=%d",
        app_config.market_fetch_interval_minutes,
        app_config.news_fetch_interval_minutes,
        app_config.rule_evaluation_interval_minutes,
    )
    logger.info(
        "Daily summary: %s at %02d:%02d %s",
        "enabled" if app_config.enable_daily_summary else "disabled",
        app_config.digest_hour,
        app_config.digest_minute,
        app_config.timezone,
    )
    logger.info("LLM summaries: %s", "enabled" if app_config.enable_llm_summaries else "disabled")
    logger.info("Ollama endpoint: %s", ollama_base_url)
    logger.info("Ollama model: %s", ollama_model)
    if report.ollama_message:
        logger.info("Ollama status: %s", report.ollama_message)

    created_defaults = [
        doc.name for doc in report.json_documents if not doc.existed_before_load
    ]
    if created_defaults:
        logger.warning(
            "Created default JSON files on first run: %s",
            ", ".join(created_defaults),
        )


def run_startup_checks(configuration: ConfigurationBundle) -> StartupReport:
    """Validate JSON persistence and probe optional dependencies."""
    json_report = validate_json_documents(DataRepository(configuration.paths))
    ollama_report = probe_ollama(configuration)
    json_report.ollama_reachable = ollama_report.ollama_reachable
    json_report.ollama_message = ollama_report.ollama_message
    log_startup_summary(configuration, json_report)
    return json_report
