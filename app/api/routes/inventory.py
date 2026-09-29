"""
app/api/routes/inventory.py

Inventory management endpoints.

Endpoints:
  GET  /inventory/{product_id}          → current stock level
  POST /inventory/{product_id}/adjust   → adjust stock (add or deduct)
  GET  /inventory/low-stock             → low-stock report

Design: product_id in the URL is the MongoDB ObjectId string of the product.
This ties inventory to products cleanly without needing a separate SKU lookup.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from pymongo.asynchronous.database import AsyncDatabase

from app.db.client import get_database
from app.repositories.inventory_repository import InventoryRepository, get_inventory_repository
from app.repositories.product_repository import ProductRepository, get_product_repository
from app.services.inventory_service import InventoryService, get_inventory_service
from app.schemas.inventory import InventoryResponse, InventoryUpdate, LowStockItem

router = APIRouter()


# ── Dependency wiring ─────────────────────────────────────────────────────────

def _inv_repo(db: AsyncDatabase = Depends(get_database)) -> InventoryRepository:
    return get_inventory_repository(db)


def _prod_repo(db: AsyncDatabase = Depends(get_database)) -> ProductRepository:
    return get_product_repository(db)


def _service(
    inv_repo: InventoryRepository = Depends(_inv_repo),
    prod_repo: ProductRepository = Depends(_prod_repo),
) -> InventoryService:
    return get_inventory_service(inv_repo, prod_repo)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get(
    "/low-stock",
    summary="Low Stock Report",
    description="Return all products with stock quantity at or below the threshold.",
    response_model=List[LowStockItem],
)
async def low_stock_report(
    threshold: int = Query(default=10, ge=0, description="Stock alert threshold"),
    service: InventoryService = Depends(_service),
) -> List[LowStockItem]:
    return await service.get_low_stock_report(threshold)


@router.get(
    "/{product_id}",
    summary="Get Inventory",
    description=(
        "Get current inventory for a product. "
        "Creates an inventory record with quantity=0 if none exists yet."
    ),
    response_model=InventoryResponse,
    responses={
        200: {"description": "Inventory record."},
        404: {"description": "Product not found."},
    },
)
async def get_inventory(
    product_id: str,
    service: InventoryService = Depends(_service),
) -> InventoryResponse:
    return await service.get_inventory(product_id)


@router.post(
    "/{product_id}/adjust",
    summary="Adjust Stock",
    description=(
        "Adjust stock quantity by a signed delta. "
        "Positive = add stock (restock). Negative = deduct stock (sale/reservation). "
        "Stock cannot go below zero."
    ),
    response_model=InventoryResponse,
    responses={
        200: {"description": "Updated inventory."},
        404: {"description": "Product not found."},
        422: {"description": "Insufficient stock for deduction."},
    },
)
async def adjust_stock(
    product_id: str,
    body: InventoryUpdate,
    service: InventoryService = Depends(_service),
) -> InventoryResponse:
    return await service.adjust_stock(product_id, body)
