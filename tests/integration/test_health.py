"""
tests/integration/test_health.py

Integration tests for GET /health.

These tests exercise the full request path:
  httpx AsyncClient → ASGI → FastAPI routing → health_check() → MongoDB ping

We test:
1. Normal case — MongoDB is reachable, response shape is correct.
2. Response fields have the expected types and values.
3. The endpoint is fast (not stuck waiting 30s for a DB timeout).
"""

import time
import pytest
from httpx import AsyncClient


class TestHealthEndpoint:
    """Tests for GET /health"""

    async def test_health_returns_200(self, client: AsyncClient) -> None:
        """The health endpoint must return HTTP 200."""
        response = await client.get("/health")
        assert response.status_code == 200

    async def test_health_response_shape(self, client: AsyncClient) -> None:
        """Response body must contain the four expected top-level keys."""
        response = await client.get("/health")
        body = response.json()

        assert "status" in body,      "Missing 'status' field"
        assert "version" in body,     "Missing 'version' field"
        assert "environment" in body, "Missing 'environment' field"
        assert "database" in body,    "Missing 'database' field"

    async def test_health_api_status_ok(self, client: AsyncClient) -> None:
        """API status field must always be 'ok' when the process is alive."""
        response = await client.get("/health")
        assert response.json()["status"] == "ok"

    async def test_health_database_connected(self, client: AsyncClient) -> None:
        """Database field must be 'ok' when MongoDB is reachable."""
        response = await client.get("/health")
        assert response.json()["database"] == "ok", (
            "Expected database='ok' but got: "
            f"{response.json()['database']}. "
            "Is MongoDB running at localhost:27017?"
        )

    async def test_health_environment_is_testing(self, client: AsyncClient) -> None:
        """
        The test fixture overrides settings so APP_ENV='testing'.
        The health endpoint must reflect the injected environment.
        """
        response = await client.get("/health")
        assert response.json()["environment"] == "testing"

    async def test_health_version_is_string(self, client: AsyncClient) -> None:
        """Version field must be a non-empty string."""
        response = await client.get("/health")
        version = response.json()["version"]
        assert isinstance(version, str)
        assert len(version) > 0

    async def test_health_content_type_is_json(self, client: AsyncClient) -> None:
        """Response must be served as application/json."""
        response = await client.get("/health")
        assert "application/json" in response.headers.get("content-type", "")

    async def test_health_is_fast(self, client: AsyncClient) -> None:
        """
        Health check must respond within 3 seconds.

        If this fails, it likely means serverSelectionTimeoutMS is too high
        or MongoDB is struggling.  The default PyMongo timeout is 30 seconds;
        we configured 5 seconds in client.py.  A healthy check should be <100ms.
        """
        start = time.monotonic()
        response = await client.get("/health")
        elapsed = time.monotonic() - start

        assert response.status_code == 200
        assert elapsed < 3.0, f"Health check took {elapsed:.2f}s — expected < 3s"
