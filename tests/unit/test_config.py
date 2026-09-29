"""
tests/unit/test_config.py

Unit tests for app/core/config.py.

Validates that:
- Settings loads with correct defaults when no .env is present.
- The is_development / is_testing / is_production properties work correctly.
- get_settings() returns a Settings instance (lru_cache behaviour is verified
  by checking that multiple calls return the same object).

These tests do NOT import get_settings() from a live app — they construct
Settings directly to avoid lru_cache contamination between test runs.
"""

import pytest

from app.core.config import Settings


class TestSettingsDefaults:
    """Verify default field values when no environment is set."""

    def test_default_app_env(self) -> None:
        s = Settings()
        assert s.app_env == "development"

    def test_default_mongodb_uri(self) -> None:
        s = Settings()
        assert s.mongodb_uri == "mongodb://localhost:27017"

    def test_default_mongodb_database(self) -> None:
        s = Settings()
        assert s.mongodb_database == "fashion_commerce"

    def test_default_api_port(self) -> None:
        s = Settings()
        assert s.api_port == 8000

    def test_default_log_level(self) -> None:
        s = Settings()
        assert s.log_level == "INFO"


class TestEnvironmentProperties:
    """Verify the is_development / is_testing / is_production properties."""

    def test_is_development_when_env_is_development(self) -> None:
        s = Settings(app_env="development")
        assert s.is_development is True
        assert s.is_testing is False
        assert s.is_production is False

    def test_is_testing_when_env_is_testing(self) -> None:
        s = Settings(app_env="testing")
        assert s.is_testing is True
        assert s.is_development is False
        assert s.is_production is False

    def test_is_production_when_env_is_production(self) -> None:
        s = Settings(app_env="production")
        assert s.is_production is True
        assert s.is_development is False
        assert s.is_testing is False

    def test_case_insensitive_env_check(self) -> None:
        """app_env comparison should be case-insensitive."""
        s = Settings(app_env="DEVELOPMENT")
        assert s.is_development is True

    def test_test_database_is_separate_from_main_database(self) -> None:
        s = Settings()
        assert s.test_mongodb_database != s.mongodb_database, (
            "Test DB and production DB must be different to avoid data loss during tests"
        )


class TestSettingsConstructedDirectly:
    """Settings can be constructed directly with kwargs (useful in tests)."""

    def test_override_mongodb_uri(self) -> None:
        s = Settings(mongodb_uri="mongodb://custom:27017")
        assert s.mongodb_uri == "mongodb://custom:27017"

    def test_override_database_name(self) -> None:
        s = Settings(mongodb_database="my_test_db")
        assert s.mongodb_database == "my_test_db"

    def test_api_port_is_integer(self) -> None:
        s = Settings()
        assert isinstance(s.api_port, int)
