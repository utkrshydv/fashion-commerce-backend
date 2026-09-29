"""
tests/unit/test_jobs.py

Unit tests for background job functions.

These tests do NOT start the APScheduler. They call the job functions
directly with a real test database, verifying the correct MongoDB mutations.

Why direct calls instead of scheduler tests?
- Scheduler timing tests are flaky and slow.
- The job logic (the important part) is fully covered by calling it directly.
- APScheduler's own test suite covers its scheduling correctness.
"""

import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from pymongo.asynchronous.database import AsyncDatabase
from bson import ObjectId

from app.utils.jobs import (
    low_stock_alert_job,
    auto_cancel_orders_job,
    LOW_STOCK_THRESHOLD,
    ORDER_EXPIRY_HOURS,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def clean_collections(db: AsyncDatabase) -> None:
    await db["products"].delete_many({})
    await db["inventory"].delete_many({})
    await db["orders"].delete_many({})
    yield
    await db["products"].delete_many({})
    await db["inventory"].delete_many({})
    await db["orders"].delete_many({})


async def _seed_product(db: AsyncDatabase, sku: str = "JOB-001", name: str = "Job Product") -> str:
    """Insert a minimal product document, return its id string."""
    result = await db["products"].insert_one({
        "sku": sku, "name": name, "brand": "Brand", "category": "Men",
        "price": 500.0, "final_price": 500.0, "discount_percentage": 0.0,
        "stock_quantity": 10, "status": "active",
        "available_sizes": ["M"], "available_colors": ["Black"],
        "image_urls": [], "description": "",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    })
    return str(result.inserted_id)


async def _seed_inventory(db: AsyncDatabase, product_id: str, quantity: int) -> None:
    await db["inventory"].insert_one({
        "product_id": product_id,
        "quantity": quantity,
        "reserved": 0,
        "low_stock_threshold": LOW_STOCK_THRESHOLD,
        "last_updated": datetime.now(timezone.utc),
    })


async def _seed_order(
    db: AsyncDatabase,
    status: str = "pending",
    hours_ago: int = 0,
    user_id: str = "job-user-001",
) -> str:
    """Insert a minimal order document."""
    created_at = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    result = await db["orders"].insert_one({
        "user_id": user_id,
        "items": [],
        "total": 100.0,
        "item_count": 1,
        "status": status,
        "shipping_address": "Test Address",
        "notes": None,
        "status_notes": None,
        "created_at": created_at,
        "updated_at": created_at,
    })
    return str(result.inserted_id)


# ── low_stock_alert_job ───────────────────────────────────────────────────────

class TestLowStockAlertJob:

    async def test_returns_empty_list_when_no_low_stock(self, db: AsyncDatabase) -> None:
        pid = await _seed_product(db)
        await _seed_inventory(db, pid, quantity=100)  # well above threshold
        result = await low_stock_alert_job(db, threshold=LOW_STOCK_THRESHOLD)
        assert result == []

    async def test_returns_alert_for_low_stock_item(self, db: AsyncDatabase) -> None:
        pid = await _seed_product(db, sku="LOW-001", name="Low Item")
        await _seed_inventory(db, pid, quantity=5)  # below threshold of 10
        result = await low_stock_alert_job(db, threshold=10)
        assert len(result) == 1
        assert result[0]["product_id"] == pid

    async def test_alert_contains_sku_and_name(self, db: AsyncDatabase) -> None:
        pid = await _seed_product(db, sku="SKU-XYZ", name="My Product")
        await _seed_inventory(db, pid, quantity=3)
        result = await low_stock_alert_job(db, threshold=10)
        assert result[0]["sku"] == "SKU-XYZ"
        assert result[0]["name"] == "My Product"

    async def test_alert_contains_quantity(self, db: AsyncDatabase) -> None:
        pid = await _seed_product(db)
        await _seed_inventory(db, pid, quantity=7)
        result = await low_stock_alert_job(db, threshold=10)
        assert result[0]["quantity"] == 7

    async def test_zero_quantity_is_included(self, db: AsyncDatabase) -> None:
        pid = await _seed_product(db)
        await _seed_inventory(db, pid, quantity=0)
        result = await low_stock_alert_job(db, threshold=10)
        assert len(result) == 1

    async def test_exactly_at_threshold_is_included(self, db: AsyncDatabase) -> None:
        pid = await _seed_product(db)
        await _seed_inventory(db, pid, quantity=10)  # exactly at threshold
        result = await low_stock_alert_job(db, threshold=10)
        assert len(result) == 1

    async def test_one_above_threshold_not_included(self, db: AsyncDatabase) -> None:
        pid = await _seed_product(db)
        await _seed_inventory(db, pid, quantity=11)
        result = await low_stock_alert_job(db, threshold=10)
        assert result == []

    async def test_multiple_low_stock_items_all_returned(self, db: AsyncDatabase) -> None:
        for i in range(3):
            pid = await _seed_product(db, sku=f"MULTI-{i:03d}")
            await _seed_inventory(db, pid, quantity=i)  # 0, 1, 2 — all < 10
        result = await low_stock_alert_job(db, threshold=10)
        assert len(result) == 3

    async def test_custom_threshold(self, db: AsyncDatabase) -> None:
        pid = await _seed_product(db)
        await _seed_inventory(db, pid, quantity=50)
        # Custom threshold of 100 should catch qty=50
        result = await low_stock_alert_job(db, threshold=100)
        assert len(result) == 1
        result_default = await low_stock_alert_job(db, threshold=10)
        assert result_default == []

    async def test_job_is_idempotent(self, db: AsyncDatabase) -> None:
        """Running the job twice produces the same result — no side effects."""
        pid = await _seed_product(db)
        await _seed_inventory(db, pid, quantity=5)
        r1 = await low_stock_alert_job(db, threshold=10)
        r2 = await low_stock_alert_job(db, threshold=10)
        assert len(r1) == len(r2) == 1


# ── auto_cancel_orders_job ────────────────────────────────────────────────────

class TestAutoCancelOrdersJob:

    async def test_returns_zero_when_no_stale_orders(self, db: AsyncDatabase) -> None:
        await _seed_order(db, status="pending", hours_ago=0)  # fresh order
        count = await auto_cancel_orders_job(db, expiry_hours=24)
        assert count == 0

    async def test_cancels_order_older_than_expiry(self, db: AsyncDatabase) -> None:
        await _seed_order(db, status="pending", hours_ago=25)  # 25h old
        count = await auto_cancel_orders_job(db, expiry_hours=24)
        assert count == 1

    async def test_cancelled_order_has_status_cancelled(self, db: AsyncDatabase) -> None:
        order_id = await _seed_order(db, status="pending", hours_ago=25)
        await auto_cancel_orders_job(db, expiry_hours=24)
        doc = await db["orders"].find_one({"_id": ObjectId(order_id)})
        assert doc["status"] == "cancelled"

    async def test_cancelled_order_has_status_notes(self, db: AsyncDatabase) -> None:
        order_id = await _seed_order(db, status="pending", hours_ago=25)
        await auto_cancel_orders_job(db, expiry_hours=24)
        doc = await db["orders"].find_one({"_id": ObjectId(order_id)})
        assert "Auto-cancelled" in doc["status_notes"]

    async def test_does_not_cancel_confirmed_order(self, db: AsyncDatabase) -> None:
        """Only pending orders are auto-cancelled."""
        await _seed_order(db, status="confirmed", hours_ago=30)
        count = await auto_cancel_orders_job(db, expiry_hours=24)
        assert count == 0

    async def test_does_not_cancel_shipped_order(self, db: AsyncDatabase) -> None:
        await _seed_order(db, status="shipped", hours_ago=30)
        count = await auto_cancel_orders_job(db, expiry_hours=24)
        assert count == 0

    async def test_does_not_cancel_fresh_pending_order(self, db: AsyncDatabase) -> None:
        await _seed_order(db, status="pending", hours_ago=1)  # only 1h old
        count = await auto_cancel_orders_job(db, expiry_hours=24)
        assert count == 0

    async def test_cancels_multiple_stale_orders(self, db: AsyncDatabase) -> None:
        for _ in range(3):
            await _seed_order(db, status="pending", hours_ago=48)
        count = await auto_cancel_orders_job(db, expiry_hours=24)
        assert count == 3

    async def test_custom_expiry_hours(self, db: AsyncDatabase) -> None:
        await _seed_order(db, status="pending", hours_ago=2)
        # With 1h expiry, a 2h-old order should be cancelled
        count = await auto_cancel_orders_job(db, expiry_hours=1)
        assert count == 1

    async def test_job_returns_count(self, db: AsyncDatabase) -> None:
        await _seed_order(db, status="pending", hours_ago=30)
        await _seed_order(db, status="pending", hours_ago=30)
        count = await auto_cancel_orders_job(db, expiry_hours=24)
        assert count == 2

    async def test_only_stale_cancelled_when_mixed(self, db: AsyncDatabase) -> None:
        """Mix of fresh and stale orders — only stale ones get cancelled."""
        await _seed_order(db, status="pending", hours_ago=1)   # fresh
        await _seed_order(db, status="pending", hours_ago=25)  # stale
        count = await auto_cancel_orders_job(db, expiry_hours=24)
        assert count == 1

    async def test_constants_have_sensible_values(self) -> None:
        assert LOW_STOCK_THRESHOLD > 0
        assert ORDER_EXPIRY_HOURS >= 1
