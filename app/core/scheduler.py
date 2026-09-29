"""
app/core/scheduler.py

APScheduler setup and job registration.

Why APScheduler?
- Async-native: works with asyncio without a separate thread.
- No external broker required: runs in-process (no Redis/RabbitMQ setup).
- Ideal for portfolio projects and small-to-medium production services.
- For higher scale or cross-instance coordination, use Celery + Redis instead.

Architecture:
- The scheduler is created once and stored on the FastAPI app's `state`.
- Lifespan handler starts it at startup and shuts it down gracefully.
- Jobs are defined in app/utils/jobs.py (pure functions, testable in isolation).

Scheduler storage: MemoryJobStore (default).
For persistent jobs that survive restarts, use SQLAlchemyJobStore or MongoDBJobStore.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.logging import get_logger
from app.utils.jobs import (
    LOW_STOCK_THRESHOLD,
    ORDER_EXPIRY_HOURS,
    low_stock_alert_job,
    auto_cancel_orders_job,
)

logger = get_logger(__name__)


def create_scheduler() -> AsyncIOScheduler:
    """
    Build and return a configured (but not yet started) AsyncIOScheduler.

    Separating creation from starting allows tests to create the scheduler
    without actually starting the background tick loop.
    """
    scheduler = AsyncIOScheduler(
        job_defaults={
            "coalesce": True,       # if a job is missed, run it once (not N times)
            "max_instances": 1,     # don't run the same job concurrently
            "misfire_grace_time": 60,  # allow up to 60s late before skipping
        }
    )
    return scheduler


def register_jobs(scheduler: AsyncIOScheduler, db) -> None:
    """
    Register all background jobs with the scheduler.

    db is the AsyncDatabase instance, passed as a closure argument so jobs
    have access to MongoDB without needing the FastAPI dependency system.

    Interval schedules (configurable for production):
    - low_stock_alert:      every 60 minutes
    - auto_cancel_orders:   every 30 minutes
    """
    # ── Job 1: Low-Stock Alert ────────────────────────────────────────────────
    scheduler.add_job(
        low_stock_alert_job,
        trigger=IntervalTrigger(minutes=60),
        id="low_stock_alert",
        name="Low Stock Alert",
        kwargs={"db": db, "threshold": LOW_STOCK_THRESHOLD},
        replace_existing=True,
    )
    logger.info("Registered job: low_stock_alert (interval=60min, threshold=%d)", LOW_STOCK_THRESHOLD)

    # ── Job 2: Auto-Cancel Stale Pending Orders ───────────────────────────────
    scheduler.add_job(
        auto_cancel_orders_job,
        trigger=IntervalTrigger(minutes=30),
        id="auto_cancel_orders",
        name="Auto-Cancel Stale Orders",
        kwargs={"db": db, "expiry_hours": ORDER_EXPIRY_HOURS},
        replace_existing=True,
    )
    logger.info(
        "Registered job: auto_cancel_orders (interval=30min, expiry=%dh)",
        ORDER_EXPIRY_HOURS,
    )
