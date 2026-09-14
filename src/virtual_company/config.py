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
    environment: str = "local"
    log_level: str = "INFO"
    log_format: str = "console"
    otel_enabled: bool = True
    otel_service_name: str = "virtual-company"
    langfuse_enabled: bool = False
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: str = "https://cloud.langfuse.com"
    langfuse_capture_io: bool = False
    llm_provider: str = "openai"
    llm_research_provider: str | None = None
    llm_extraction_provider: str | None = None
    openai_api_key: SecretStr | None = None
    openai_research_model: str = "gpt-5.6-terra"
    openai_extraction_model: str = "gpt-5.6-luna"
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-sonnet-5"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide application settings."""
    return Settings()
