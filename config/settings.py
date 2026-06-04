"""Environment-backed runtime settings."""

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
    ollama_base_url: str = Field(
        default="http://ollama:11434",
        alias="OLLAMA_BASE_URL",
    )
    ollama_model: str = Field(default="llama3.1:8b", alias="OLLAMA_MODEL")
    timezone: str = Field(default="Asia/Hong_Kong", alias="TZ")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    data_dir: str = Field(default="/app/data", alias="DATA_DIR")
    log_dir: str = Field(default="/app/logs", alias="LOG_DIR")
