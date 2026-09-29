"""
app/repositories/product_repository.py

MongoDB data access layer for the products collection.

Responsibilities:
- All MongoDB queries for products live here.
- No business logic — only data access.
- Wraps unexpected pymongo errors in DatabaseException so callers
  (the service layer) never receive raw driver exceptions.

Design notes:
- Returns raw dicts (MongoDB documents) rather than Pydantic models.
  The service layer converts them. This keeps the repository decoupled
  from the schema layer and lets us return projections freely.
- Uses MongoDB's `_id` (ObjectId) for lookups internally.
  The service converts string IDs to ObjectId before calling the repository.
- The `products` collection name is the single point of truth in this file.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ASCENDING, DESCENDING
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.core.exceptions import (
    DatabaseException,
    DuplicateSKUException,
    ProductNotFoundException,
)
from app.core.logging import get_logger

logger = get_logger(__name__)

COLLECTION = "products"


class ProductRepository:
    """
    Repository for the `products` collection.

    Instantiated by the service layer, receiving the database handle
    via dependency injection. This makes the repository trivially testable —
    tests inject a test database, no mocking required.
    """

    def __init__(self, db: AsyncDatabase) -> None:
        self._collection: AsyncCollection = db[COLLECTION]

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _to_object_id(product_id: str) -> ObjectId:
        """Convert a string product_id to bson.ObjectId, raising 404 on invalid format."""
        try:
            return ObjectId(product_id)
        except (InvalidId, Exception):
            raise ProductNotFoundException(
                f"Product with id '{product_id}' not found.",
                detail={"product_id": product_id},
            )

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)

    # ── Write Operations ──────────────────────────────────────────────────────

    async def insert_one(self, document: Dict[str, Any]) -> Dict[str, Any]:
        """
        Insert a new product document.

        Returns the inserted document with `_id` populated.
        Raises DuplicateSKUException if the SKU already exists
        (enforced by the sku_unique index).
        """
        try:
            result = await self._collection.insert_one(document)
            document["_id"] = result.inserted_id
            logger.info("Product inserted: _id=%s sku=%s", result.inserted_id, document.get("sku"))
            return document
        except DuplicateKeyError:
            raise DuplicateSKUException(
                f"A product with SKU '{document.get('sku')}' already exists.",
                detail={"sku": document.get("sku")},
            )
        except PyMongoError as exc:
            logger.error("insert_one failed: %s", exc)
            raise DatabaseException("Failed to create product.") from exc

    async def update_one(
        self, product_id: str, update_fields: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Update a product by id.

        Uses `$set` so only provided fields are changed — not a full document replace.
        Always sets `updated_at` to now.
        Returns the updated document, or raises ProductNotFoundException.
        """
        oid = self._to_object_id(product_id)
        update_fields["updated_at"] = self._utcnow()

        try:
            updated = await self._collection.find_one_and_update(
                {"_id": oid},
                {"$set": update_fields},
                return_document=True,  # return the document AFTER the update
            )
        except PyMongoError as exc:
            logger.error("update_one failed for %s: %s", product_id, exc)
            raise DatabaseException("Failed to update product.") from exc

        if updated is None:
            raise ProductNotFoundException(
                f"Product with id '{product_id}' not found.",
                detail={"product_id": product_id},
            )
        return updated

    async def delete_one(self, product_id: str) -> bool:
        """
        Delete a product by id.

        Returns True if deleted, raises ProductNotFoundException if not found.
        """
        oid = self._to_object_id(product_id)
        try:
            result = await self._collection.delete_one({"_id": oid})
        except PyMongoError as exc:
            logger.error("delete_one failed for %s: %s", product_id, exc)
            raise DatabaseException("Failed to delete product.") from exc

        if result.deleted_count == 0:
            raise ProductNotFoundException(
                f"Product with id '{product_id}' not found.",
                detail={"product_id": product_id},
            )
        logger.info("Product deleted: _id=%s", product_id)
        return True

    # ── Read Operations ───────────────────────────────────────────────────────

    async def find_by_id(self, product_id: str) -> Dict[str, Any]:
        """Return a single product by id, raising ProductNotFoundException if missing."""
        oid = self._to_object_id(product_id)
        try:
            doc = await self._collection.find_one({"_id": oid})
        except PyMongoError as exc:
            logger.error("find_by_id failed for %s: %s", product_id, exc)
            raise DatabaseException("Failed to retrieve product.") from exc

        if doc is None:
            raise ProductNotFoundException(
                f"Product with id '{product_id}' not found.",
                detail={"product_id": product_id},
            )
        return doc

    async def find_by_sku(self, sku: str) -> Optional[Dict[str, Any]]:
        """Return a product by SKU, or None if not found."""
        try:
            return await self._collection.find_one({"sku": sku})
        except PyMongoError as exc:
            logger.error("find_by_sku failed for %s: %s", sku, exc)
            raise DatabaseException("Failed to retrieve product.") from exc

    async def find_many(
        self,
        filters: Dict[str, Any],
        sort_field: str = "created_at",
        sort_dir: int = DESCENDING,
        skip: int = 0,
        limit: int = 20,
        projection: Optional[Dict[str, int]] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Paginated product list with filtering and sorting.

        Returns (documents, total_count).

        `total_count` is the count of ALL matching documents (ignoring pagination),
        needed to calculate total pages on the client.

        We run two queries:
        1. count_documents(filters) — fast if filters use indexed fields
        2. find(filters).sort().skip().limit() — the actual page

        Why not use aggregation $facet?
        For typical catalog queries the two-query approach is simpler and
        fast enough. $facet becomes useful when you need more complex
        computed metadata alongside results.
        """
        try:
            total = await self._collection.count_documents(filters)
            cursor = (
                self._collection
                .find(filters, projection=projection)
                .sort(sort_field, sort_dir)
                .skip(skip)
                .limit(limit)
            )
            docs = await cursor.to_list(length=limit)
            return docs, total
        except PyMongoError as exc:
            logger.error("find_many failed: %s", exc)
            raise DatabaseException("Failed to list products.") from exc


def get_product_repository(db: AsyncDatabase) -> ProductRepository:
    """
    FastAPI dependency factory.

    Usage:
        async def route(repo = Depends(get_product_repository)):
            ...

    The service layer uses this same factory.
    """
    return ProductRepository(db)
