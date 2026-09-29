"""
app/core/config.py

Application configuration loaded from environment variables using Pydantic Settings.
All secrets and runtime options should be controlled from here.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from functools import lru_cache


class Settings(BaseSettings):
    """
    Central configuration object.

    Pydantic Settings will:
    1. Read values from a .env file (if present).
    2. Override those values with actual environment variables.
    3. Validate all values on startup — the app will refuse to start if
       a required setting is missing or invalid.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────────────
    app_name: str = Field(default="Fashion Commerce Backend")
    app_version: str = Field(default="0.1.0")
    app_env: str = Field(default="development")
    log_level: str = Field(default="INFO")

    # ── MongoDB ───────────────────────────────────────────────────────────
    mongodb_uri: str = Field(default="mongodb://localhost:27017")
    mongodb_database: str = Field(default="fashion_commerce")

    # ── API Server ────────────────────────────────────────────────────────
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)

    # ── Testing ───────────────────────────────────────────────────────────
    test_mongodb_database: str = Field(default="fashion_commerce_test")

    @property
    def is_development(self) -> bool:
        return self.app_env.lower() == "development"

    @property
    def is_testing(self) -> bool:
        return self.app_env.lower() == "testing"

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return the singleton Settings instance.

    @lru_cache ensures Settings is only constructed once per process.
    FastAPI dependency injection can call this repeatedly without
    repeatedly parsing the .env file or environment.
    """
    return Settings()
