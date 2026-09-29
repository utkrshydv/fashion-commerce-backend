"""
tests/conftest.py

Shared pytest fixtures for the entire test suite.

Testing architecture
────────────────────
We use httpx.AsyncClient with ASGITransport to make requests through the
full FastAPI middleware and routing stack without binding a real TCP port.

Event loop strategy
───────────────────
pytest-asyncio creates a new event loop for each test function by default
(asyncio_mode="auto", scope="function").  PyMongo's AsyncMongoClient binds
to the event loop it was created on and cannot be used from a different loop.

Therefore all async fixtures that create a MongoDB client must be
function-scoped — they live and die within the same event loop as the test.

Dependency injection strategy
──────────────────────────────
We override two FastAPI dependencies per test:
  - get_database  → returns a test AsyncDatabase handle
  - get_settings  → returns test Settings (app_env="testing")

This means:
  - The app's lifespan (connect_to_mongo) is never called during tests.
  - Tests are fully isolated from the development database.
  - Any route that calls Depends(get_database) or Depends(get_settings)
    receives the test values.

Fixtures available
──────────────────
- test_settings   : Settings pointing at fashion_commerce_test (session scope)
- client          : AsyncClient with overridden DB + settings (function scope)
- db              : AsyncDatabase handle for direct assertions (function scope)
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import Settings, get_settings
from app.db.client import get_database
from app.db.indexes import ensure_indexes
from app.main import create_app


# ── Test Settings (session scope — no DB, safe to share) ─────────────────────

@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """
    Return a Settings instance pointing at the isolated test database.

    Constructed directly (not from .env) so CI without a .env file works.
    Session-scoped: created once, shared by all tests.
    """
    return Settings(
        app_env="testing",
        mongodb_uri="mongodb://localhost:27017",
        mongodb_database="fashion_commerce_test",
        log_level="WARNING",
    )


# ── Per-test MongoDB connection (function scope) ───────────────────────────────

@pytest_asyncio.fixture(scope="function")
async def db(test_settings: Settings) -> AsyncDatabase:
    """
    Function-scoped AsyncDatabase handle for the test database.

    A new AsyncMongoClient is created per test function so it binds to
    the correct event loop (pytest-asyncio creates a new loop per function).

    Use this fixture to:
    - Seed data before a test:   await db["products"].insert_one({...})
    - Assert after an API call:  doc = await db["products"].find_one(...)
    - Clean up after a test:     await db["products"].delete_many({})
    """
    mc = AsyncMongoClient(
        test_settings.mongodb_uri,
        serverSelectionTimeoutMS=5000,
    )
    # Verify connectivity on first use.
    await mc.admin.command("ping")

    database = mc[test_settings.mongodb_database]

    # Ensure indexes exist (idempotent — safe to call every test).
    await ensure_indexes(database)

    yield database

    # Close the client after the test.
    # In pymongo 4.18+, AsyncMongoClient.close() is a coroutine.
    await mc.close()


# ── Per-test HTTP client ──────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="function")
async def client(db: AsyncDatabase, test_settings: Settings) -> AsyncClient:
    """
    Function-scoped AsyncClient for integration tests.

    The app is created fresh for each test.  Two dependencies are overridden:
      - get_database  → the function-scoped test DB (same event loop)
      - get_settings  → the test Settings (app_env="testing")

    The app's lifespan is NOT invoked — the test fixtures manage the DB
    connection so we avoid the event loop binding problem.
    """
    app = create_app()
    app.dependency_overrides[get_database] = lambda: db
    app.dependency_overrides[get_settings] = lambda: test_settings

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://testserver",
    ) as ac:
        yield ac
