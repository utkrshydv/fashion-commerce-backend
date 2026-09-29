"""
app/db/indexes.py

MongoDB index definitions for all collections.

Index strategy:
- Indexes are created idempotently at application startup
  (ensure_indexes() is called from the lifespan handler in main.py).
- PyMongo's create_index / create_indexes are idempotent — calling
  them when the index already exists is a no-op.
- Only indexes that directly benefit a real query are defined here.
  Unnecessary indexes slow down writes and consume memory.

Collection index rationale is documented in learning.md.
"""

from pymongo.asynchronous.database import AsyncDatabase
from pymongo import ASCENDING, DESCENDING, TEXT

from app.core.logging import get_logger

logger = get_logger(__name__)


async def ensure_indexes(db: AsyncDatabase) -> None:
    """
    Create all collection indexes.
    Safe to call on every startup — existing indexes are not recreated.
    """
    await _create_product_indexes(db)
    await _create_order_indexes(db)
    await _create_cart_indexes(db)
    await _create_inventory_indexes(db)
    logger.info("All MongoDB indexes ensured.")


async def _create_product_indexes(db: AsyncDatabase) -> None:
    products = db["products"]

    # Unique constraint on SKU — enforced at the DB level, not just application level.
    await products.create_index([("sku", ASCENDING)], unique=True, name="sku_unique")

    # Compound index for the most common catalog list query:
    # filter by category + sort by price or created_at.
    await products.create_index(
        [("category", ASCENDING), ("price", ASCENDING)],
        name="category_price",
    )

    # Brand filter
    await products.create_index([("brand", ASCENDING)], name="brand")

    # Status filter (active / inactive)
    await products.create_index([("status", ASCENDING)], name="status")

    # Price range queries
    await products.create_index([("price", ASCENDING)], name="price")

    # Most-recent-first ordering
    await products.create_index([("created_at", DESCENDING)], name="created_at_desc")

    # Full-text search index on name + description + brand
    await products.create_index(
        [("name", TEXT), ("description", TEXT), ("brand", TEXT)],
        name="text_search",
        weights={"name": 10, "brand": 5, "description": 1},
    )

    logger.info("Product indexes ensured.")


async def _create_order_indexes(db: AsyncDatabase) -> None:
    orders = db["orders"]

    # Most common query: all orders for a specific user, newest first.
    await orders.create_index(
        [("user_id", ASCENDING), ("created_at", DESCENDING)],
        name="user_id_created_at",
    )

    # Order status filtering (e.g. admin dashboard showing pending orders).
    await orders.create_index([("status", ASCENDING)], name="status")

    logger.info("Order indexes ensured.")


async def _create_cart_indexes(db: AsyncDatabase) -> None:
    carts = db["carts"]

    # Cart lookup is always by user_id — make it a unique index since
    # each user has exactly one cart.
    await carts.create_index([("user_id", ASCENDING)], unique=True, name="user_id_unique")

    logger.info("Cart indexes ensured.")


async def _create_inventory_indexes(db: AsyncDatabase) -> None:
    inventory = db["inventory"]

    # Inventory is looked up by product_id — enforce uniqueness.
    await inventory.create_index(
        [("product_id", ASCENDING)], unique=True, name="product_id_unique"
    )

    # Low-stock monitoring queries.
    await inventory.create_index([("quantity", ASCENDING)], name="quantity")

    logger.info("Inventory indexes ensured.")
