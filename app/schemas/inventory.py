"""
app/schemas/inventory.py

Pydantic schemas for the inventory domain.

Inventory is a separate collection from products.  Each product_id has
exactly one inventory record (enforced by the unique index on product_id).

The separation of inventory from products allows:
- Independent scaling of stock operations vs. catalog reads.
- Inventory updates (stock adjust) don't lock the product document.
- Future: inventory could be sharded by warehouse location.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class InventoryResponse(BaseModel):
    """Full inventory record as returned by GET /inventory/{product_id}."""
    id: str = Field(alias="_id")
    product_id: str
    quantity: int = Field(description="Current available stock quantity")
    reserved: int = Field(default=0, description="Units reserved for pending orders")
    low_stock_threshold: int = Field(
        default=10,
        description="Alert threshold — quantity below this is considered low stock",
    )
    is_low_stock: bool = Field(
        description="True when quantity <= low_stock_threshold"
    )
    last_updated: datetime

    model_config = {"populate_by_name": True, "arbitrary_types_allowed": True}


class InventoryUpdate(BaseModel):
    """
    Request body for adjusting stock.

    delta > 0 → add stock (restock)
    delta < 0 → deduct stock (sale/reservation)
    """
    delta: int = Field(..., description="Stock change. Positive=add, negative=deduct.")
    reason: Optional[str] = Field(
        None, max_length=200, description="Optional reason for the adjustment"
    )


class LowStockItem(BaseModel):
    """Lightweight representation of an inventory record in the low-stock report."""
    product_id: str
    quantity: int
    low_stock_threshold: int
    is_low_stock: bool

    model_config = {"populate_by_name": True}
