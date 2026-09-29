"""
app/api/routes/health.py

Health check endpoint.

Used by:
- Docker HEALTHCHECK directive
- Load balancers / orchestrators (Kubernetes liveness/readiness probes)
- Developer sanity checks

GET /health returns:
  - API status (always "ok" if the process is alive)
  - Database connectivity status
  - Application version
"""

from fastapi import APIRouter, Depends
from pymongo.asynchronous.database import AsyncDatabase

from app.db.client import get_database
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.get(
    "/health",
    summary="Health Check",
    description=(
        "Returns the operational status of the API and its MongoDB connection. "
        "Used by Docker health checks and monitoring tools."
    ),
    tags=["Health"],
    response_model=dict,
)
async def health_check(db: AsyncDatabase = Depends(get_database)) -> dict:
    """
    Lightweight health check.

    Performs a MongoDB 'ping' command to verify the database is reachable.
    Returns 200 if both API and DB are healthy; reports DB status separately
    so that an upstream monitor can distinguish between the two failure modes.
    """
    settings = get_settings()

    db_status = "unreachable"
    try:
        await db.command("ping")
        db_status = "ok"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Health check DB ping failed: %s", exc)

    return {
        "status": "ok",
        "version": settings.app_version,
        "environment": settings.app_env,
        "database": db_status,
    }
