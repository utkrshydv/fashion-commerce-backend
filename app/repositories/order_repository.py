"""
app/repositories/order_repository.py

MongoDB data access layer for the orders collection.

Order documents are append-mostly: created once, then only status is updated.
This makes the repository relatively simple compared to cart (no array mutations).

Key design:
- _id is an ObjectId; exposed as a 24-char hex string in the API.
- Queries by user_id use the compound (user_id, created_at DESC) index.
- Status updates are simple $set operations.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import DESCENDING
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import PyMongoError

from app.core.exceptions import DatabaseException, OrderNotFoundException
from app.core.logging import get_logger

logger = get_logger(__name__)

COLLECTION = "orders"


class OrderRepository:

    def __init__(self, db: AsyncDatabase) -> None:
        self._col: AsyncCollection = db[COLLECTION]

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _to_oid(order_id: str) -> ObjectId:
        try:
            return ObjectId(order_id)
        except (InvalidId, Exception):
            raise OrderNotFoundException(
                f"Order '{order_id}' not found.",
                detail={"order_id": order_id},
            )

    @staticmethod
    def _str_id(doc: Dict[str, Any]) -> Dict[str, Any]:
        if doc and "_id" in doc:
            doc["_id"] = str(doc["_id"])
        return doc

    # ── Write ─────────────────────────────────────────────────────────────────

    async def insert_one(self, document: Dict[str, Any]) -> Dict[str, Any]:
        """Insert a new order and return the document with _id as string."""
        try:
            result = await self._col.insert_one(document)
            document["_id"] = str(result.inserted_id)
            logger.info("Order created: _id=%s user_id=%s", document["_id"], document.get("user_id"))
            return document
        except PyMongoError as exc:
            logger.error("Order insert failed: %s", exc)
            raise DatabaseException("Failed to create order.") from exc

    async def update_status(
        self,
        order_id: str,
        status: str,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update order status. Returns updated document or raises OrderNotFoundException."""
        oid = self._to_oid(order_id)
        update: Dict[str, Any] = {
            "status": status,
            "updated_at": self._utcnow(),
        }
        if notes is not None:
            update["status_notes"] = notes

        try:
            updated = await self._col.find_one_and_update(
                {"_id": oid},
                {"$set": update},
                return_document=True,
            )
        except PyMongoError as exc:
            raise DatabaseException("Failed to update order status.") from exc

        if updated is None:
            raise OrderNotFoundException(
                f"Order '{order_id}' not found.",
                detail={"order_id": order_id},
            )
        return self._str_id(updated)

    # ── Read ──────────────────────────────────────────────────────────────────

    async def find_by_id(self, order_id: str) -> Dict[str, Any]:
        oid = self._to_oid(order_id)
        try:
            doc = await self._col.find_one({"_id": oid})
        except PyMongoError as exc:
            raise DatabaseException("Failed to retrieve order.") from exc
        if doc is None:
            raise OrderNotFoundException(
                f"Order '{order_id}' not found.",
                detail={"order_id": order_id},
            )
        return self._str_id(doc)

    async def find_by_user(
        self,
        user_id: str,
        skip: int = 0,
        limit: int = 20,
        status_filter: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Return paginated orders for a user, newest first."""
        filters: Dict[str, Any] = {"user_id": user_id}
        if status_filter:
            filters["status"] = status_filter

        projection = {
            "items": 0,          # exclude items array for list view
            "shipping_address": 0,
            "notes": 0,
            "status_notes": 0,
        }

        try:
            total = await self._col.count_documents(filters)
            cursor = (
                self._col
                .find(filters, projection=projection)
                .sort("created_at", DESCENDING)
                .skip(skip)
                .limit(limit)
            )
            docs = await cursor.to_list(length=limit)
            return [self._str_id(d) for d in docs], total
        except PyMongoError as exc:
            raise DatabaseException("Failed to list orders.") from exc


def get_order_repository(db: AsyncDatabase) -> OrderRepository:
    return OrderRepository(db)
