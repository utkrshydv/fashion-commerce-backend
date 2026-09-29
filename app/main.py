"""
app/main.py

FastAPI application factory and lifespan handler.

This file has three responsibilities:
1. Creates the FastAPI application instance via create_app().
2. Registers the lifespan context manager (startup / shutdown logic).
3. Registers all routers under their URL prefixes.

The lifespan context manager is the correct FastAPI >= 0.93 pattern for
managing resources that live for the entire process lifetime (database
connections, background schedulers, ML models, etc.).
It replaces the deprecated @app.on_event("startup") / ("shutdown").
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.exceptions import AppException
from app.core.logging import configure_logging, get_logger
from app.db.client import connect_to_mongo, close_mongo_connection, get_database
from app.db.indexes import ensure_indexes

# ── Route imports ─────────────────────────────────────────────────────────────
from app.api.routes import health
from app.api.routes import products
from app.api.routes import search

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager.

    Code before `yield`  → runs once at startup, before the first request.
    Code after  `yield`  → runs once at shutdown, after the last request.

    If anything in the startup block raises an exception, Uvicorn will log
    the error and exit instead of serving traffic with a broken dependency.
    """
    # ── Startup ───────────────────────────────────────────────────────────────
    configure_logging()
    settings = get_settings()

    logger.info(
        "Starting %s v%s [env=%s]",
        settings.app_name,
        settings.app_version,
        settings.app_env,
    )

    # Connect to MongoDB and verify connectivity (raises on failure).
    await connect_to_mongo()

    # Create all collection indexes idempotently.
    db = get_database()
    await ensure_indexes(db)

    logger.info("Application startup complete — ready to serve requests.")

    yield  # ── Application is running ────────────────────────────────────────

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("Shutting down...")
    await close_mongo_connection()
    logger.info("Shutdown complete.")


def create_app() -> FastAPI:
    """
    Application factory.

    Returning a configured FastAPI instance from a function (instead of
    defining it at module level) makes it easy for tests to create a fresh,
    isolated app instance without side effects from the production singleton.
    """
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "RESTful backend for a fashion e-commerce platform. "
            "Supports product catalog, search, shopping cart, orders, "
            "and inventory management."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_tags=[
            {"name": "Health",    "description": "Service health and readiness checks."},
            {"name": "Products", "description": "Product catalog management."},
            {"name": "Search",   "description": "Full-text product search."},
        ],
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    # Development: allow all origins so a local frontend can connect easily.
    # Production: lock this down to the actual frontend domain.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.is_development else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Global exception handlers ─────────────────────────────────────────────

    @app.exception_handler(AppException)
    async def app_exception_handler(
        request: Request, exc: AppException
    ) -> JSONResponse:
        """
        Converts any AppException subclass into a consistent JSON response.

        Services and repositories raise typed domain exceptions
        (e.g. ProductNotFoundException, InsufficientStockException).
        They never raise HTTPException directly — that would couple the
        business logic to the HTTP transport layer.
        This single handler translates domain errors to HTTP in one place.
        """
        logger.warning(
            "AppException [%s] %s | path=%s",
            exc.error_code,
            exc.message,
            request.url.path,
        )
        body: dict = {"error": exc.error_code, "message": exc.message}
        if exc.detail is not None:
            body["detail"] = exc.detail
        return JSONResponse(status_code=exc.status_code, content=body)

    @app.exception_handler(RuntimeError)
    async def runtime_error_handler(
        request: Request, exc: RuntimeError
    ) -> JSONResponse:
        """
        Handles the RuntimeError raised by get_database() when called before
        the DB connection is established (e.g. during a health check race on
        startup).  Returns 503 Service Unavailable so the caller knows the
        service is temporarily not ready, not permanently broken.
        """
        logger.error("RuntimeError on %s: %s", request.url.path, exc)
        return JSONResponse(
            status_code=503,
            content={
                "error": "service_unavailable",
                "message": "Service is not ready yet. Please retry.",
            },
        )

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(health.router)
    app.include_router(products.router, prefix="/products", tags=["Products"])
    app.include_router(search.router,   prefix="/search",   tags=["Search"])

    # Routers registered in later stages:
    # app.include_router(cart.router,     prefix="/cart",     tags=["Cart"])
    # app.include_router(orders.router,   prefix="/orders",   tags=["Orders"])
    # app.include_router(inventory.router,prefix="/inventory",tags=["Inventory"])

    return app


# Module-level app instance — Uvicorn imports this as `app.main:app`.
app = create_app()
