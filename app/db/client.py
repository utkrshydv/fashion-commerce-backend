"""
app/db/client.py

MongoDB client lifecycle management.

Design decisions:
- A single AsyncIOMotorClient / AsyncMongoClient is created once at
  startup and reused for the entire process lifetime.
- FastAPI's lifespan context manager (in main.py) calls
  connect_to_mongo() on startup and close_mongo_connection() on shutdown.
- All repositories receive the database handle via dependency injection,
  not by importing a global variable directly.  This makes unit testing
  straightforward — tests can inject a different database handle.
"""

from __future__ import annotations

from typing import Optional
from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Module-level references — set during application startup.
_client: Optional[AsyncMongoClient] = None
_database: Optional[AsyncDatabase] = None


async def connect_to_mongo() -> None:
    """
    Open the MongoDB connection and verify connectivity.
    Called by the FastAPI lifespan handler on startup.
    """
    global _client, _database

    settings = get_settings()
    logger.info("Connecting to MongoDB at %s", settings.mongodb_uri)

    _client = AsyncMongoClient(settings.mongodb_uri)
    _database = _client[settings.mongodb_database]

    # Verify the connection is actually reachable before serving traffic.
    await _client.admin.command("ping")
    logger.info("MongoDB connected — database: %s", settings.mongodb_database)


async def close_mongo_connection() -> None:
    """
    Close the MongoDB connection cleanly.
    Called by the FastAPI lifespan handler on shutdown.
    """
    global _client, _database

    if _client is not None:
        _client.close()
        _client = None
        _database = None
        logger.info("MongoDB connection closed.")


def get_database() -> AsyncDatabase:
    """
    Return the active database handle.

    Raises RuntimeError if called before connect_to_mongo().
    Used as a FastAPI dependency so route handlers and services
    never access the module-level variable directly.
    """
    if _database is None:
        raise RuntimeError(
            "Database is not connected. "
            "Ensure connect_to_mongo() was called during application startup."
        )
    return _database
