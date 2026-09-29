"""
app/schemas/cart.py

Pydantic schemas for the shopping cart domain.

Cart design:
- One cart per user (user_id is the lookup key, unique index).
- A cart contains a list of CartItem, each referencing a product by its _id.
- The cart stores a snapshot of price/name at add-time.
  This is intentional: if a product's price changes after it's added to cart,
  the customer sees the price they originally saw (common e-commerce behaviour).
- total is computed from items, never stored — it's always fresh.

Authentication:
  Stage 5 has no auth. user_id comes from the X-User-ID HTTP header.
  Stage 7 (Auth) will replace this with JWT claims.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class CartItem(BaseModel):
    """A single product line in the cart."""
    product_id: str
    sku: str
    name: str
    quantity: int = Field(ge=1)
    unit_price: float = Field(description="Price at time of adding to cart (snapshot)")
    subtotal: float = Field(description="unit_price * quantity, computed")


class CartItemAdd(BaseModel):
    """Request body for adding an item to the cart."""
    product_id: str = Field(..., description="MongoDB ObjectId of the product")
    quantity: int = Field(..., ge=1, le=100, description="Quantity to add (1–100)")


class CartItemUpdate(BaseModel):
    """Request body for updating item quantity."""
    quantity: int = Field(..., ge=1, le=100, description="New quantity (1–100)")


class CartResponse(BaseModel):
    """Full cart response including all items and computed total."""
    id: str = Field(alias="_id")
    user_id: str
    items: List[CartItem]
    total: float = Field(description="Sum of all item subtotals")
    item_count: int = Field(description="Total number of individual items (sum of quantities)")
    created_at: datetime
    updated_at: datetime

    model_config = {"populate_by_name": True, "arbitrary_types_allowed": True}
