"""
app/schemas/order.py

Pydantic schemas for the orders domain.

Order lifecycle:
  pending → confirmed → shipped → delivered
                └──────────────────────────→ cancelled

Rules:
- Only pending orders can be cancelled.
- Once shipped, the order cannot go backwards.
- These rules are enforced in the service layer (InvalidStatusTransitionException).

An order is a permanent snapshot of a cart at checkout time:
- Items, prices, and quantities are frozen into the order document.
- The cart is cleared after order placement.
- Even if a product is deleted later, the order retains full item details.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class OrderStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


# Valid status transitions: current_status → [allowed next statuses]
VALID_TRANSITIONS: dict[str, list[str]] = {
    "pending":   ["confirmed", "cancelled"],
    "confirmed": ["shipped",   "cancelled"],
    "shipped":   ["delivered"],
    "delivered": [],
    "cancelled": [],
}


class OrderItem(BaseModel):
    """Snapshot of a single cart line at checkout time."""
    product_id: str
    sku: str
    name: str
    quantity: int
    unit_price: float
    subtotal: float


class OrderCreate(BaseModel):
    """
    Request body for POST /orders.

    Minimal — the order is built from the authenticated user's cart.
    Only shipping address is required from the client.
    """
    shipping_address: str = Field(
        ..., min_length=5, max_length=500,
        description="Delivery address for this order"
    )
    notes: Optional[str] = Field(None, max_length=300)


class OrderStatusUpdate(BaseModel):
    """Request body for PUT /orders/{id}/status."""
    status: OrderStatus = Field(..., description="New order status")
    notes: Optional[str] = Field(None, max_length=300)


class OrderResponse(BaseModel):
    """Full order document returned by all order endpoints."""
    id: str = Field(alias="_id")
    user_id: str
    items: List[OrderItem]
    total: float
    item_count: int
    status: OrderStatus
    shipping_address: str
    notes: Optional[str] = None
    status_notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"populate_by_name": True, "arbitrary_types_allowed": True}


class OrderListItem(BaseModel):
    """Lightweight order representation for list responses."""
    id: str = Field(alias="_id")
    user_id: str
    total: float
    item_count: int
    status: OrderStatus
    created_at: datetime

    model_config = {"populate_by_name": True, "arbitrary_types_allowed": True}
