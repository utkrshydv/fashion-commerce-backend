"""
app/db/client.py

MongoDB client lifecycle management.

Design decisions:
- A single AsyncMongoClient is created once at startup and reused for the
  entire process lifetime.  Creating a new client per request would be
  extremely expensive and exhaust connection pool limits quickly.
- FastAPI's lifespan context manager (in main.py) calls connect_to_mongo()
  on startup and close_mongo_connection() on shutdown.
- All repositories receive the database handle via dependency injection,
  not by importing the module-level _database variable directly.  This makes
  unit testing straightforward — tests can inject a different database handle
  by overriding the FastAPI dependency.

serverSelectionTimeoutMS=5000:
  By default, PyMongo waits up to 30 seconds to select a server when
  running a command.  We reduce this to 5 s so that a misconfigured
  MONGODB_URI causes a fast, obvious startup failure rather than a 30-second
  hang that looks like a deadlock.
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

# How long to wait for a MongoDB server to respond before giving up.
_SERVER_SELECTION_TIMEOUT_MS = 5_000  # 5 seconds


async def connect_to_mongo() -> None:
    """
    Open the MongoDB connection and verify connectivity.
    Called by the FastAPI lifespan handler on startup.

    Raises:
        pymongo.errors.ServerSelectionTimeoutError: if MongoDB is unreachable
            within SERVER_SELECTION_TIMEOUT_MS milliseconds.
    """
    global _client, _database

    settings = get_settings()
    logger.info("Connecting to MongoDB at %s", settings.mongodb_uri)

    _client = AsyncMongoClient(
        settings.mongodb_uri,
        serverSelectionTimeoutMS=_SERVER_SELECTION_TIMEOUT_MS,
    )
    _database = _client[settings.mongodb_database]

    # Issue a ping to verify the connection is actually reachable before
    # the app starts serving traffic.  If this fails, the exception
    # propagates out of the lifespan handler and Uvicorn will refuse to start.
    await _client.admin.command("ping")
    logger.info(
        "MongoDB connected — database: %s (timeout: %dms)",
        settings.mongodb_database,
        _SERVER_SELECTION_TIMEOUT_MS,
    )


async def close_mongo_connection() -> None:
    """
    Close the MongoDB connection cleanly.
    Called by the FastAPI lifespan handler on shutdown.
    """
    global _client, _database

    if _client is not None:
        await _client.close()
        _client = None
        _database = None
        logger.info("MongoDB connection closed.")


def get_database() -> AsyncDatabase:
    """
    Return the active database handle.

    Raises RuntimeError if called before connect_to_mongo() completes.
    Used as a FastAPI dependency so route handlers and services never
    access the module-level variable directly.

    Usage in a route:
        async def my_route(db: AsyncDatabase = Depends(get_database)):
            ...
    """
    if _database is None:
        raise RuntimeError(
            "Database is not connected. "
            "Ensure connect_to_mongo() was called during application startup."
        )
    return _database
