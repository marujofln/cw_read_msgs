"""Application settings loaded from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration for the Chatwoot read-sync service."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    chatwoot_base_url: str
    chatwoot_api_token: str
    chatwoot_account_ids: list[int]
    evolution_api_url: str | None = None
    evolution_api_key: str | None = None
    redis_url: str | None = None
    log_level: str = "INFO"
    port: int = 3100


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings (singleton)."""
    return Settings()  # type: ignore[call-arg]
