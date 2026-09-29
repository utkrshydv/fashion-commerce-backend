"""
app/services/product_service.py

Business logic layer for the product domain.

Responsibilities:
- Orchestrate repository calls
- Apply business rules (SKU uniqueness, price validation, computed fields)
- Convert raw MongoDB dicts to typed Pydantic response schemas
- Never touch HTTP concerns (no status codes, no Request objects)

What belongs here vs. the repository:
- "Does a product with this SKU already exist?" → business rule → service
- "Insert a document into products collection"  → data access → repository
- "Calculate final_price from price + discount" → business rule → service
- "Run find() with filters and sort"            → data access → repository
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from pymongo import ASCENDING, DESCENDING

from app.repositories.product_repository import ProductRepository
from app.schemas.product import (
    ProductCreate,
    ProductListItem,
    ProductResponse,
    ProductStatus,
    ProductUpdate,
)
from app.schemas.common import PaginatedResponse
from app.schemas.search import SearchResult, SearchResponse
from app.core.logging import get_logger

logger = get_logger(__name__)

# Valid sort fields exposed through the API
_ALLOWED_SORT_FIELDS = {"price", "name", "created_at", "brand", "discount_percentage"}
_DEFAULT_SORT_FIELD = "created_at"


class ProductService:
    """
    Service layer for product operations.

    Receives a ProductRepository and delegates all DB calls to it.
    All methods return Pydantic schemas, never raw dicts.
    """

    def __init__(self, repo: ProductRepository) -> None:
        self._repo = repo

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_final_price(price: float, discount_percentage: float) -> float:
        """
        final_price = price * (1 - discount_percentage / 100)

        Rounded to 2 decimal places to avoid floating-point drift.
        Stored in the DB document for query efficiency (e.g. sorting by final price).
        """
        return round(price * (1 - discount_percentage / 100), 2)

    @staticmethod
    def _doc_to_response(doc: Dict[str, Any]) -> ProductResponse:
        """Convert a raw MongoDB document to a ProductResponse schema."""
        return ProductResponse.model_validate(doc)

    @staticmethod
    def _doc_to_list_item(doc: Dict[str, Any]) -> ProductListItem:
        return ProductListItem.model_validate(doc)

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)

    # ── Create ────────────────────────────────────────────────────────────────

    async def create_product(self, data: ProductCreate) -> ProductResponse:
        """
        Create a new product.

        Business rules:
        1. SKU must be unique (enforced by DB index + DuplicateSKUException).
        2. final_price is computed here and stored alongside price.
           Storing it avoids recomputing it on every read.

        Flow:
          service.create_product(data)
            → _compute_final_price(price, discount)
            → repo.insert_one(document)
            → convert to ProductResponse
        """
        final_price = self._compute_final_price(data.price, data.discount_percentage)
        now = self._utcnow()

        document = {
            "sku": data.sku,
            "name": data.name,
            "description": data.description,
            "brand": data.brand,
            "category": data.category,
            "price": data.price,
            "discount_percentage": data.discount_percentage,
            "final_price": final_price,
            "available_sizes": data.available_sizes,
            "available_colors": data.available_colors,
            "image_urls": data.image_urls,
            "stock_quantity": data.stock_quantity,
            "status": data.status.value,
            "created_at": now,
            "updated_at": now,
        }

        inserted = await self._repo.insert_one(document)
        return self._doc_to_response(inserted)

    # ── Read Single ───────────────────────────────────────────────────────────

    async def get_product(self, product_id: str) -> ProductResponse:
        """Return a single product by id. Raises ProductNotFoundException if missing."""
        doc = await self._repo.find_by_id(product_id)
        return self._doc_to_response(doc)

    # ── Read List (with filters + pagination) ─────────────────────────────────

    async def list_products(
        self,
        page: int = 1,
        limit: int = 20,
        category: Optional[str] = None,
        brand: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        status: Optional[str] = None,
        sort_by: str = _DEFAULT_SORT_FIELD,
        sort_order: str = "desc",
    ) -> PaginatedResponse[ProductListItem]:
        """
        Return a paginated list of products with optional filters.

        Filter logic:
        - All filters are additive (AND semantics).
        - price filters apply to `final_price` (the discounted price),
          not the base price, so the customer sees correct filtering.
        - status defaults to None (all statuses returned).

        Sort validation:
        - Only fields in _ALLOWED_SORT_FIELDS are accepted.
        - Invalid sort fields fall back to created_at to avoid query errors.
        """
        filters: Dict[str, Any] = {}

        if category:
            filters["category"] = category
        if brand:
            filters["brand"] = brand
        if status:
            filters["status"] = status

        # Price range filter on final_price (what the customer actually pays)
        if min_price is not None or max_price is not None:
            price_filter: Dict[str, float] = {}
            if min_price is not None:
                price_filter["$gte"] = min_price
            if max_price is not None:
                price_filter["$lte"] = max_price
            filters["final_price"] = price_filter

        # Validate and resolve sort field
        sort_field = sort_by if sort_by in _ALLOWED_SORT_FIELDS else _DEFAULT_SORT_FIELD
        sort_dir = DESCENDING if sort_order.lower() == "desc" else ASCENDING

        skip = (page - 1) * limit

        # Projection: exclude large fields for list responses
        projection = {"description": 0, "image_urls": 0}

        docs, total = await self._repo.find_many(
            filters=filters,
            sort_field=sort_field,
            sort_dir=sort_dir,
            skip=skip,
            limit=limit,
            projection=projection,
        )

        items = [self._doc_to_list_item(d) for d in docs]
        return PaginatedResponse.build(items=items, total=total, page=page, limit=limit)

    # ── Update ────────────────────────────────────────────────────────────────

    async def update_product(
        self, product_id: str, data: ProductUpdate
    ) -> ProductResponse:
        """
        Partial update a product.

        Business rules:
        1. SKU cannot be changed (it is not part of ProductUpdate schema).
        2. If price or discount changes, final_price is recomputed.
        3. Only non-None fields from the request are applied (partial update).

        How partial update works:
        - `data.model_dump(exclude_none=True)` returns only the fields
          the client actually sent (skips None/omitted fields).
        - These fields are passed to `repo.update_one()` which uses `$set`,
          leaving all other document fields unchanged.
        """
        update_fields = data.model_dump(exclude_none=True)

        if not update_fields:
            # Nothing to update — return current state
            return await self.get_product(product_id)

        # Recompute final_price whenever price OR discount changes
        if "price" in update_fields or "discount_percentage" in update_fields:
            # If only one changed, we need the current value of the other
            if "price" not in update_fields or "discount_percentage" not in update_fields:
                current = await self._repo.find_by_id(product_id)
                update_fields.setdefault("price", current["price"])
                update_fields.setdefault("discount_percentage", current["discount_percentage"])

            update_fields["final_price"] = self._compute_final_price(
                update_fields["price"],
                update_fields["discount_percentage"],
            )

        # Convert enum to string value for storage
        if "status" in update_fields and hasattr(update_fields["status"], "value"):
            update_fields["status"] = update_fields["status"].value

        updated = await self._repo.update_one(product_id, update_fields)
        return self._doc_to_response(updated)

    # ── Delete ────────────────────────────────────────────────────────────────

    async def delete_product(self, product_id: str) -> bool:
        """
        Delete a product permanently.

        Returns True on success, raises ProductNotFoundException if not found.

        Production note: in a real system, you would likely soft-delete
        (set status="archived") rather than hard-delete, to preserve
        order history references. Hard delete is fine for this project.
        """
        return await self._repo.delete_one(product_id)

    # ── Search ────────────────────────────────────────────────────────────────

    async def search_products(
        self,
        query: str,
        page: int = 1,
        limit: int = 20,
        category: Optional[str] = None,
        status: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
    ) -> SearchResponse:
        """
        Full-text search across product name, description, and brand.

        Uses MongoDB $text search with relevance scoring.  Results are
        returned in score-descending order (best match first) and support
        additional AND filters (category, status, price range).

        Minimum query length of 2 chars is enforced to prevent sending
        an empty $text search to MongoDB (which raises an error).
        """
        extra_filters: Dict[str, Any] = {}
        if category:
            extra_filters["category"] = category
        if status:
            extra_filters["status"] = status
        if min_price is not None or max_price is not None:
            pf: Dict[str, float] = {}
            if min_price is not None:
                pf["$gte"] = min_price
            if max_price is not None:
                pf["$lte"] = max_price
            extra_filters["final_price"] = pf

        skip = (page - 1) * limit
        docs, total = await self._repo.text_search(
            query=query,
            extra_filters=extra_filters,
            skip=skip,
            limit=limit,
        )

        items = [
            SearchResult(
                **ProductListItem.model_validate(d).model_dump(by_alias=True),
                score=d.get("score"),
            )
            for d in docs
        ]
        return SearchResponse.build(
            items=items, total=total, page=page, limit=limit, query=query
        )


def get_product_service(repo: ProductRepository) -> ProductService:
    """FastAPI dependency factory for ProductService."""
    return ProductService(repo)
