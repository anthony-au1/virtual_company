"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://virtual_company:virtual_company@localhost:5432/virtual_company"
)


class Settings(BaseSettings):
    """Runtime settings for infrastructure integrations."""

    model_config = SettingsConfigDict(extra="ignore")

    database_url: str = DEFAULT_DATABASE_URL
    openai_api_key: SecretStr | None = None
    openai_model: str | None = None


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide application settings."""
    return Settings()
