"""Environment-backed runtime settings.

Loaded from .env via pydantic-settings. Required: TELEGRAM_BOT_TOKEN.
TELEGRAM_CHAT_ID bootstraps the first developer when users.json is empty.
Optional: OLLAMA_*, HKU_API_*, DATA_DIR, LOG_DIR, TZ, LOG_LEVEL.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RuntimeSettings(BaseSettings):
    """Secrets and service endpoints supplied via environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: str = Field(alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(alias="TELEGRAM_CHAT_ID")
    ollama_base_url: str | None = Field(default=None, alias="OLLAMA_BASE_URL")
    ollama_model: str | None = Field(default=None, alias="OLLAMA_MODEL")
    timezone: str = Field(default="Asia/Hong_Kong", alias="TZ")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    data_dir: str = Field(default="/app/data", alias="DATA_DIR")
    log_dir: str = Field(default="/app/logs", alias="LOG_DIR")
    finnhub_api_key: str | None = Field(default=None, alias="FINNHUB_API_KEY")
    hku_api_key: str | None = Field(default=None, alias="HKU_API_KEY")
    hku_api_base_url: str | None = Field(default=None, alias="HKU_API_BASE_URL")
    hku_claude_model: str | None = Field(default=None, alias="HKU_CLAUDE_MODEL")
    hku_claude_models: str | None = Field(default=None, alias="HKU_CLAUDE_MODELS")
    hku_openai_model: str | None = Field(default=None, alias="HKU_OPENAI_MODEL")
    hku_openai_models: str | None = Field(default=None, alias="HKU_OPENAI_MODELS")
    hku_openai_api_version: str | None = Field(default=None, alias="HKU_OPENAI_API_VERSION")
