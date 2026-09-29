"""
app/services/order_service.py

Business logic for order placement and management.

The most critical operation here is place_order(), which must:
1. Validate the cart is non-empty.
2. For each item: check stock in the inventory collection.
3. Deduct stock for each item atomically.
4. Create the order document.
5. Clear the user's cart.

Atomicity note:
In a production system this multi-step operation would use a MongoDB
multi-document transaction (session.start_transaction()).  We deliberately
skip transactions here to keep the code readable for a learning project.
The compensating action (if order creation fails after stock deduction) would
be to re-add the deducted stock.  This is documented in learning.md.

State machine:
  pending → confirmed → shipped → delivered
  pending → cancelled
  confirmed → cancelled
  (shipped/delivered/cancelled are terminal — no further transitions)
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import List, Optional

from app.repositories.cart_repository import CartRepository
from app.repositories.inventory_repository import InventoryRepository
from app.repositories.order_repository import OrderRepository
from app.schemas.cart import CartResponse
from app.schemas.order import (
    OrderCreate,
    OrderListItem,
    OrderResponse,
    OrderStatus,
    OrderStatusUpdate,
    VALID_TRANSITIONS,
)
from app.schemas.common import PaginatedResponse
from app.core.exceptions import (
    CartNotFoundException,
    InvalidStatusTransitionException,
    InsufficientStockException,
    OrderNotFoundException,
    ValidationException,
)
from app.core.logging import get_logger

logger = get_logger(__name__)


class OrderService:

    def __init__(
        self,
        order_repo: OrderRepository,
        cart_repo: CartRepository,
        inv_repo: InventoryRepository,
    ) -> None:
        self._orders = order_repo
        self._cart = cart_repo
        self._inv = inv_repo

    @staticmethod
    def _to_response(doc: dict) -> OrderResponse:
        return OrderResponse.model_validate(doc)

    @staticmethod
    def _to_list_item(doc: dict) -> OrderListItem:
        return OrderListItem.model_validate(doc)

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)

    # ── Place Order ───────────────────────────────────────────────────────────

    async def place_order(self, user_id: str, data: OrderCreate) -> OrderResponse:
        """
        Checkout flow — converts a cart into an order.

        Steps:
        1. Fetch the cart; raise ValidationException if empty.
        2. For each item: verify stock exists in the inventory collection.
           We check BEFORE deducting to give a clean error if any item fails.
        3. Deduct inventory for all items (using atomic $inc).
        4. Build and insert the order document.
        5. Clear the cart.

        If step 4 fails (database error) after step 3, inventory has been
        deducted without an order being created.  In production, step 3+4
        would be wrapped in a MongoDB session transaction.  For this project,
        we accept this known limitation and document it in learning.md.
        """
        # Step 1: Validate cart
        cart = await self._cart.find_by_user(user_id)
        if cart is None or not cart.get("items"):
            raise ValidationException(
                "Cannot place an order with an empty cart.",
                detail={"user_id": user_id},
            )

        items = cart["items"]

        # Step 2: Pre-flight stock check (read-only, no mutations yet)
        for item in items:
            inv = await self._inv.find_by_product_id(item["product_id"])
            available = inv.get("quantity", 0) if inv else 0
            if available < item["quantity"]:
                raise InsufficientStockException(
                    f"'{item['name']}' has insufficient stock. "
                    f"Requested: {item['quantity']}, available: {available}.",
                    detail={
                        "product_id": item["product_id"],
                        "sku": item["sku"],
                        "requested": item["quantity"],
                        "available": available,
                    },
                )

        # Step 3: Deduct inventory
        for item in items:
            await self._inv.adjust_stock(item["product_id"], -item["quantity"])

        # Step 4: Create order document
        now = self._utcnow()
        total = cart.get("total", 0.0)
        item_count = cart.get("item_count", 0)

        order_doc = {
            "user_id": user_id,
            "items": [
                {
                    "product_id": i["product_id"],
                    "sku": i["sku"],
                    "name": i["name"],
                    "quantity": i["quantity"],
                    "unit_price": i["unit_price"],
                    "subtotal": i["subtotal"],
                }
                for i in items
            ],
            "total": total,
            "item_count": item_count,
            "status": OrderStatus.PENDING.value,
            "shipping_address": data.shipping_address,
            "notes": data.notes,
            "status_notes": None,
            "created_at": now,
            "updated_at": now,
        }

        inserted = await self._orders.insert_one(order_doc)

        # Step 5: Clear the cart
        await self._cart.clear_cart(user_id)

        logger.info("Order placed: order_id=%s user_id=%s total=%.2f", inserted["_id"], user_id, total)
        return self._to_response(inserted)

    # ── Get Single Order ──────────────────────────────────────────────────────

    async def get_order(self, user_id: str, order_id: str) -> OrderResponse:
        """
        Get a single order. Verifies ownership (order belongs to this user).
        """
        doc = await self._orders.find_by_id(order_id)
        if doc["user_id"] != user_id:
            # Return 404 rather than 403 to avoid revealing that the order exists
            raise OrderNotFoundException(
                f"Order '{order_id}' not found.",
                detail={"order_id": order_id},
            )
        return self._to_response(doc)

    # ── List Orders ───────────────────────────────────────────────────────────

    async def list_orders(
        self,
        user_id: str,
        page: int = 1,
        limit: int = 20,
        status_filter: Optional[str] = None,
    ) -> PaginatedResponse[OrderListItem]:
        skip = (page - 1) * limit
        docs, total = await self._orders.find_by_user(
            user_id, skip=skip, limit=limit, status_filter=status_filter
        )
        items = [self._to_list_item(d) for d in docs]
        return PaginatedResponse.build(items=items, total=total, page=page, limit=limit)

    # ── Update Status ─────────────────────────────────────────────────────────

    async def update_order_status(
        self, user_id: str, order_id: str, data: OrderStatusUpdate
    ) -> OrderResponse:
        """
        Advance the order through the status state machine.

        The VALID_TRANSITIONS dict defines which moves are allowed.
        Any attempt to make an invalid transition raises
        InvalidStatusTransitionException (HTTP 400).
        """
        doc = await self._orders.find_by_id(order_id)
        if doc["user_id"] != user_id:
            raise OrderNotFoundException(
                f"Order '{order_id}' not found.",
                detail={"order_id": order_id},
            )

        current_status = doc["status"]
        new_status = data.status.value
        allowed = VALID_TRANSITIONS.get(current_status, [])

        if new_status not in allowed:
            raise InvalidStatusTransitionException(
                f"Cannot transition order from '{current_status}' to '{new_status}'. "
                f"Allowed transitions: {allowed or ['none']}.",
                detail={
                    "current_status": current_status,
                    "requested_status": new_status,
                    "allowed": allowed,
                },
            )

        updated = await self._orders.update_status(order_id, new_status, data.notes)
        return self._to_response(updated)


def get_order_service(
    order_repo: OrderRepository,
    cart_repo: CartRepository,
    inv_repo: InventoryRepository,
) -> OrderService:
    return OrderService(order_repo, cart_repo, inv_repo)
