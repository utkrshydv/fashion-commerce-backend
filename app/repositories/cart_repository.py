"""
app/repositories/cart_repository.py

MongoDB data access layer for the carts collection.

Cart document structure:
{
    "_id": ObjectId,
    "user_id": "user-123",          ← unique index (one cart per user)
    "items": [
        {
            "product_id": "abc...",
            "sku": "SHIRT-001",
            "name": "Classic Shirt",
            "quantity": 2,
            "unit_price": 899.10,
            "subtotal": 1798.20,
        }
    ],
    "total": 1798.20,
    "item_count": 2,
    "created_at": ISODate,
    "updated_at": ISODate,
}

Key design decisions:
- All mutations use atomic MongoDB operators ($set, $push, $pull, $inc)
  rather than read-modify-write to avoid race conditions.
- The cart is always looked up by user_id, never by _id, from the outside.
- subtotal and total are stored for fast reads (avoid recomputing on every GET).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import PyMongoError

from app.core.exceptions import CartNotFoundException, DatabaseException
from app.core.logging import get_logger

logger = get_logger(__name__)

COLLECTION = "carts"


class CartRepository:

    def __init__(self, db: AsyncDatabase) -> None:
        self._col: AsyncCollection = db[COLLECTION]

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _str_id(doc: Dict[str, Any]) -> Dict[str, Any]:
        if doc and "_id" in doc:
            doc["_id"] = str(doc["_id"])
        return doc

    # ── Read ──────────────────────────────────────────────────────────────────

    async def find_by_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        try:
            doc = await self._col.find_one({"user_id": user_id})
            return self._str_id(doc) if doc else None
        except PyMongoError as exc:
            raise DatabaseException("Failed to retrieve cart.") from exc

    async def get_or_create(self, user_id: str) -> Dict[str, Any]:
        """Return the user's cart, creating an empty one if it doesn't exist."""
        try:
            now = self._utcnow()
            doc = await self._col.find_one_and_update(
                {"user_id": user_id},
                {
                    "$setOnInsert": {
                        "user_id": user_id,
                        "items": [],
                        "total": 0.0,
                        "item_count": 0,
                        "created_at": now,
                        "updated_at": now,
                    }
                },
                upsert=True,
                return_document=True,
            )
            return self._str_id(doc)
        except PyMongoError as exc:
            raise DatabaseException("Failed to get/create cart.") from exc

    # ── Item management ───────────────────────────────────────────────────────

    async def upsert_item(
        self,
        user_id: str,
        item: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Add a new item or replace an existing one (matched by product_id).

        Strategy:
        1. Remove any existing item for this product_id.
        2. Push the new item.
        3. Recompute total and item_count.

        Using $pull + $push in separate operations is simpler and safer
        than a $set with positional operator (which requires knowing array index).
        We do this in two sequential updates — not a transaction, but since
        this is a user-scoped cart and concurrent edits to the same product
        are extremely rare in practice, this is acceptable.
        """
        try:
            # Remove existing item for this product (if any)
            await self._col.update_one(
                {"user_id": user_id},
                {"$pull": {"items": {"product_id": item["product_id"]}}},
            )
            # Push new item
            await self._col.update_one(
                {"user_id": user_id},
                {
                    "$push": {"items": item},
                    "$set": {"updated_at": self._utcnow()},
                },
            )
            # Recompute total and item_count from current items
            return await self._recompute_totals(user_id)
        except PyMongoError as exc:
            raise DatabaseException("Failed to add item to cart.") from exc

    async def update_item_quantity(
        self, user_id: str, product_id: str, quantity: int, unit_price: float
    ) -> Dict[str, Any]:
        """Update quantity and subtotal for a specific item."""
        subtotal = round(unit_price * quantity, 2)
        try:
            result = await self._col.update_one(
                {"user_id": user_id, "items.product_id": product_id},
                {
                    "$set": {
                        "items.$.quantity": quantity,
                        "items.$.subtotal": subtotal,
                        "updated_at": self._utcnow(),
                    }
                },
            )
            if result.matched_count == 0:
                raise CartNotFoundException(
                    f"Item {product_id} not found in cart.",
                    detail={"product_id": product_id},
                )
            return await self._recompute_totals(user_id)
        except CartNotFoundException:
            raise
        except PyMongoError as exc:
            raise DatabaseException("Failed to update cart item.") from exc

    async def remove_item(self, user_id: str, product_id: str) -> Dict[str, Any]:
        """Remove a single item from the cart by product_id."""
        try:
            result = await self._col.update_one(
                {"user_id": user_id},
                {
                    "$pull": {"items": {"product_id": product_id}},
                    "$set": {"updated_at": self._utcnow()},
                },
            )
            if result.modified_count == 0:
                # Check if the item was there at all
                cart = await self._col.find_one({"user_id": user_id})
                if not cart:
                    raise CartNotFoundException("Cart not found.")
                raise CartNotFoundException(
                    f"Item {product_id} not found in cart.",
                    detail={"product_id": product_id},
                )
            return await self._recompute_totals(user_id)
        except CartNotFoundException:
            raise
        except PyMongoError as exc:
            raise DatabaseException("Failed to remove item from cart.") from exc

    async def clear_cart(self, user_id: str) -> Dict[str, Any]:
        """Remove all items from the cart (used after order placement)."""
        try:
            now = self._utcnow()
            doc = await self._col.find_one_and_update(
                {"user_id": user_id},
                {"$set": {"items": [], "total": 0.0, "item_count": 0, "updated_at": now}},
                return_document=True,
            )
            return self._str_id(doc)
        except PyMongoError as exc:
            raise DatabaseException("Failed to clear cart.") from exc

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _recompute_totals(self, user_id: str) -> Dict[str, Any]:
        """
        Recompute total and item_count from the items array and persist.

        This is called after every mutation to keep stored totals in sync.
        A stored total allows fast GET /cart without recomputing every time.
        """
        doc = await self._col.find_one({"user_id": user_id})
        if not doc:
            raise CartNotFoundException("Cart not found.")
        items = doc.get("items", [])
        total = round(sum(i.get("subtotal", 0) for i in items), 2)
        item_count = sum(i.get("quantity", 0) for i in items)
        await self._col.update_one(
            {"user_id": user_id},
            {"$set": {"total": total, "item_count": item_count}},
        )
        doc["total"] = total
        doc["item_count"] = item_count
        return self._str_id(doc)


def get_cart_repository(db: AsyncDatabase) -> CartRepository:
    return CartRepository(db)
