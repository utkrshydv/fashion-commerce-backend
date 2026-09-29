"""
app/main.py

FastAPI application factory and lifespan handler.

This file does three things:
1. Creates the FastAPI application instance.
2. Registers the lifespan context manager which runs startup/shutdown logic.
3. Registers all routers (API routes) under their URL prefixes.

The lifespan context manager is the correct FastAPI pattern for:
- Connecting to databases
- Creating indexes
- Closing connections on shutdown
(Replaces deprecated @app.on_event("startup") / @app.on_event("shutdown"))
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.exceptions import AppException
from app.core.logging import configure_logging, get_logger
from app.db.client import connect_to_mongo, close_mongo_connection
from app.db.indexes import ensure_indexes
from app.db.client import get_database

# ── Route imports ─────────────────────────────────────────────────────────────
from app.api.routes import health

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager.

    Everything before `yield` runs at startup.
    Everything after `yield` runs at shutdown.
    """
    # ── Startup ───────────────────────────────────────────────────────────────
    configure_logging()
    settings = get_settings()

    logger.info(
        "Starting %s v%s [%s]",
        settings.app_name,
        settings.app_version,
        settings.app_env,
    )

    await connect_to_mongo()

    db = get_database()
    await ensure_indexes(db)

    logger.info("Application startup complete. Ready to serve requests.")

    yield  # ── Application is running ────────────────────────────────────────

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("Application shutting down...")
    await close_mongo_connection()
    logger.info("Shutdown complete.")


def create_app() -> FastAPI:
    """
    Application factory.

    Returns a configured FastAPI instance.
    Using a factory function (rather than a module-level `app = FastAPI()`)
    makes it straightforward to create isolated app instances in tests.
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
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    # In production, restrict origins to your actual frontend domain.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.is_development else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Global exception handler ──────────────────────────────────────────────
    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        """
        Convert any AppException subclass into a consistent JSON error response.
        This is the single place where domain exceptions become HTTP responses.
        """
        logger.warning(
            "AppException [%s] %s — path=%s",
            exc.error_code,
            exc.message,
            request.url.path,
        )
        body: dict = {"error": exc.error_code, "message": exc.message}
        if exc.detail is not None:
            body["detail"] = exc.detail
        return JSONResponse(status_code=exc.status_code, content=body)

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(health.router)
    # Additional routers registered in later stages:
    # app.include_router(products.router, prefix="/products", tags=["Products"])
    # app.include_router(search.router,   prefix="/search",   tags=["Search"])
    # app.include_router(cart.router,     prefix="/cart",     tags=["Cart"])
    # app.include_router(orders.router,   prefix="/orders",   tags=["Orders"])
    # app.include_router(inventory.router,prefix="/inventory",tags=["Inventory"])

    return app


# ── Module-level app instance used by Uvicorn ─────────────────────────────────
app = create_app()
