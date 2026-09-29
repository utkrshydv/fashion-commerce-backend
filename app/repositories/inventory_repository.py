"""
app/repositories/inventory_repository.py

MongoDB data access layer for the inventory collection.

Design notes:
- One inventory document per product (product_id is a unique index key).
- All stock adjustments use $inc (atomic increment) not read-then-write,
  preventing race conditions under concurrent requests.
- find_or_create: the first time inventory is queried for a product, a record
  is created with quantity=0. This lazy initialization means we don't need a
  migration to create inventory records for every product.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pymongo import ASCENDING
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import PyMongoError

from app.core.exceptions import DatabaseException, InventoryNotFoundException, InsufficientStockException
from app.core.logging import get_logger

logger = get_logger(__name__)

COLLECTION = "inventory"
DEFAULT_LOW_STOCK_THRESHOLD = 10


class InventoryRepository:

    def __init__(self, db: AsyncDatabase) -> None:
        self._col: AsyncCollection = db[COLLECTION]

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _enrich(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """Add computed is_low_stock field to raw document."""
        doc["is_low_stock"] = doc.get("quantity", 0) <= doc.get(
            "low_stock_threshold", DEFAULT_LOW_STOCK_THRESHOLD
        )
        return doc

    # ── Read ──────────────────────────────────────────────────────────────────

    async def find_by_product_id(self, product_id: str) -> Optional[Dict[str, Any]]:
        """Return the inventory record for a product, or None."""
        try:
            doc = await self._col.find_one({"product_id": product_id})
            return self._enrich(doc) if doc else None
        except PyMongoError as exc:
            raise DatabaseException("Failed to retrieve inventory.") from exc

    async def get_or_create(self, product_id: str) -> Dict[str, Any]:
        """
        Return the inventory record, creating it with quantity=0 if missing.

        Uses find_one_and_update with upsert=True so the create is atomic:
        no risk of two concurrent requests both trying to insert.
        """
        try:
            doc = await self._col.find_one_and_update(
                {"product_id": product_id},
                {
                    "$setOnInsert": {
                        "product_id": product_id,
                        "quantity": 0,
                        "reserved": 0,
                        "low_stock_threshold": DEFAULT_LOW_STOCK_THRESHOLD,
                        "last_updated": self._utcnow(),
                    }
                },
                upsert=True,
                return_document=True,
            )
            # Ensure _id is a string for schema compatibility
            if doc and "_id" in doc:
                doc["_id"] = str(doc["_id"])
            return self._enrich(doc)
        except PyMongoError as exc:
            raise DatabaseException("Failed to get/create inventory.") from exc

    async def find_low_stock(self, threshold: int = DEFAULT_LOW_STOCK_THRESHOLD) -> List[Dict[str, Any]]:
        """Return all inventory records where quantity <= threshold."""
        try:
            cursor = self._col.find({"quantity": {"$lte": threshold}}).sort("quantity", ASCENDING)
            docs = await cursor.to_list(length=200)
            return [self._enrich(d) for d in docs]
        except PyMongoError as exc:
            raise DatabaseException("Failed to fetch low-stock items.") from exc

    # ── Write ─────────────────────────────────────────────────────────────────

    async def adjust_stock(self, product_id: str, delta: int) -> Dict[str, Any]:
        """
        Atomically adjust stock by delta.

        Uses $inc which is atomic at the MongoDB server level — two concurrent
        requests adjusting stock will both be applied correctly without reading
        the current value first.

        Raises InsufficientStockException if the result would go negative.
        We enforce this with a filter: only apply the update if
        quantity + delta >= 0.

        If the inventory record doesn't exist, creates it first via get_or_create.
        """
        # Ensure record exists
        await self.get_or_create(product_id)

        if delta < 0:
            # Deduction: only allow if sufficient stock
            updated = await self._col.find_one_and_update(
                {"product_id": product_id, "quantity": {"$gte": abs(delta)}},
                {
                    "$inc": {"quantity": delta},
                    "$set": {"last_updated": self._utcnow()},
                },
                return_document=True,
            )
            if updated is None:
                # Either product not found, or insufficient stock
                current = await self._col.find_one({"product_id": product_id})
                available = current.get("quantity", 0) if current else 0
                raise InsufficientStockException(
                    f"Insufficient stock. Requested: {abs(delta)}, available: {available}.",
                    detail={"product_id": product_id, "requested": abs(delta), "available": available},
                )
        else:
            # Addition: always allowed
            updated = await self._col.find_one_and_update(
                {"product_id": product_id},
                {
                    "$inc": {"quantity": delta},
                    "$set": {"last_updated": self._utcnow()},
                },
                return_document=True,
            )

        if updated and "_id" in updated:
            updated["_id"] = str(updated["_id"])
        return self._enrich(updated)


def get_inventory_repository(db: AsyncDatabase) -> InventoryRepository:
    return InventoryRepository(db)
