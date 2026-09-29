"""
app/utils/jobs.py

Background job functions — the actual work done by scheduled tasks.

Design principles:
- Each job is a plain async function that accepts a database parameter.
- Jobs do NOT depend on the FastAPI request cycle or APScheduler internals.
- This makes them independently unit-testable without starting the scheduler.
- The scheduler (app/core/scheduler.py) is responsible only for WHEN to call these.

Jobs:
1. low_stock_alert_job      — logs (simulates alerting) products below threshold
2. auto_cancel_orders_job   — cancels pending orders older than TTL hours
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any

from pymongo.asynchronous.database import AsyncDatabase

from app.core.logging import get_logger

logger = get_logger(__name__)

# ── Configuration constants ────────────────────────────────────────────────────

LOW_STOCK_THRESHOLD = 10          # items with qty <= this are "low stock"
ORDER_EXPIRY_HOURS = 24           # pending orders older than this are auto-cancelled


# ── Job 1: Low-Stock Alert ─────────────────────────────────────────────────────

async def low_stock_alert_job(db: AsyncDatabase, threshold: int = LOW_STOCK_THRESHOLD) -> List[Dict[str, Any]]:
    """
    Find all inventory records with quantity <= threshold and log them.

    In a real system, this would:
    - Query low-stock items (done here)
    - Look up product names/SKUs
    - Send email/Slack notifications to the ops team

    Returns the list of low-stock items (useful for testing and for an
    optional admin API endpoint that shows the last alert snapshot).

    This job is idempotent — running it twice has no side effects.
    """
    inventory_col = db["inventory"]
    products_col = db["products"]

    cursor = inventory_col.find({"quantity": {"$lte": threshold}})
    low_items = await cursor.to_list(length=500)

    if not low_items:
        logger.info("[low_stock_alert] No low-stock items found (threshold=%d)", threshold)
        return []

    # Enrich with product names for the alert
    alerts = []
    for item in low_items:
        product_id = item.get("product_id")
        qty = item.get("quantity", 0)

        # Look up the product name for a human-readable alert
        try:
            from bson import ObjectId
            product = await products_col.find_one(
                {"_id": ObjectId(product_id)},
                projection={"name": 1, "sku": 1},
            )
            name = product.get("name", "Unknown") if product else "Unknown"
            sku = product.get("sku", "?") if product else "?"
        except Exception:
            name, sku = "Unknown", "?"

        alert = {
            "product_id": product_id,
            "sku": sku,
            "name": name,
            "quantity": qty,
            "threshold": threshold,
        }
        alerts.append(alert)

        logger.warning(
            "[LOW STOCK ALERT] SKU=%s | name=%r | qty=%d | threshold=%d",
            sku, name, qty, threshold,
        )

    logger.info(
        "[low_stock_alert] Alert complete: %d low-stock items found (threshold=%d)",
        len(alerts), threshold,
    )
    return alerts


# ── Job 2: Auto-Cancel Expired Pending Orders ──────────────────────────────────

async def auto_cancel_orders_job(
    db: AsyncDatabase,
    expiry_hours: int = ORDER_EXPIRY_HOURS,
) -> int:
    """
    Cancel all pending orders that have been in 'pending' status for longer
    than `expiry_hours` hours.

    Business reason:
    - Pending orders hold a payment intent but haven't been confirmed yet.
    - After 24h without payment confirmation, they should be auto-cancelled
      to release inventory reservation and clean up stale records.

    Why NOT restore inventory here:
    - In this project, inventory is deducted at order placement (not at confirmation).
    - Auto-cancel would need to add back the deducted stock.
    - This is intentionally left as a documented TODO to avoid over-engineering
      the learning project; in production this would be a compensating transaction.

    Returns the number of orders cancelled (useful for testing and monitoring).
    """
    orders_col = db["orders"]
    cutoff = datetime.now(timezone.utc) - timedelta(hours=expiry_hours)

    result = await orders_col.update_many(
        {
            "status": "pending",
            "created_at": {"$lt": cutoff},
        },
        {
            "$set": {
                "status": "cancelled",
                "status_notes": f"Auto-cancelled: pending for more than {expiry_hours} hours.",
                "updated_at": datetime.now(timezone.utc),
            }
        },
    )

    cancelled_count = result.modified_count

    if cancelled_count > 0:
        logger.warning(
            "[auto_cancel_orders] Cancelled %d stale pending orders (expiry=%dh, cutoff=%s)",
            cancelled_count, expiry_hours, cutoff.isoformat(),
        )
    else:
        logger.info(
            "[auto_cancel_orders] No stale pending orders found (expiry=%dh)", expiry_hours
        )

    return cancelled_count
