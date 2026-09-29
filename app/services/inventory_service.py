"""
app/services/inventory_service.py

Business logic for the inventory domain.

Responsibilities:
- Validate that a product exists before creating/modifying inventory.
- Delegate all DB operations to InventoryRepository.
- Convert raw dicts to typed Pydantic response schemas.
"""

from __future__ import annotations

from typing import List

from app.repositories.inventory_repository import InventoryRepository
from app.repositories.product_repository import ProductRepository
from app.schemas.inventory import InventoryResponse, InventoryUpdate, LowStockItem
from app.core.logging import get_logger

logger = get_logger(__name__)


class InventoryService:

    def __init__(
        self,
        inv_repo: InventoryRepository,
        product_repo: ProductRepository,
    ) -> None:
        self._inv = inv_repo
        self._prod = product_repo

    @staticmethod
    def _to_response(doc: dict) -> InventoryResponse:
        return InventoryResponse.model_validate(doc)

    async def get_inventory(self, product_id: str) -> InventoryResponse:
        """
        Get inventory for a product.

        Validates the product exists first (raises ProductNotFoundException if not).
        Creates the inventory record with quantity=0 on first access (lazy init).
        """
        await self._prod.find_by_id(product_id)  # raises 404 if product missing
        doc = await self._inv.get_or_create(product_id)
        return self._to_response(doc)

    async def adjust_stock(
        self, product_id: str, update: InventoryUpdate
    ) -> InventoryResponse:
        """
        Adjust stock by a signed delta.

        Positive delta = restock (add stock).
        Negative delta = deduct (sale, manual adjustment).

        Business rules:
        - Product must exist.
        - Stock cannot go negative (raises InsufficientStockException).
        """
        await self._prod.find_by_id(product_id)  # raises 404 if product missing
        doc = await self._inv.adjust_stock(product_id, update.delta)
        logger.info(
            "Stock adjusted: product_id=%s delta=%+d reason=%s",
            product_id, update.delta, update.reason or "—",
        )
        return self._to_response(doc)

    async def get_low_stock_report(self, threshold: int = 10) -> List[LowStockItem]:
        """Return all products with quantity <= threshold."""
        docs = await self._inv.find_low_stock(threshold)
        return [LowStockItem.model_validate(d) for d in docs]


def get_inventory_service(
    inv_repo: InventoryRepository,
    product_repo: ProductRepository,
) -> InventoryService:
    return InventoryService(inv_repo, product_repo)
