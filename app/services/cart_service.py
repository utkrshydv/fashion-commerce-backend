"""
app/services/cart_service.py

Business logic for the shopping cart.

Responsibilities:
- Validate that added products exist and are active.
- Snapshot price at add-time (crucial: if price changes later, cart shows old price).
- Enforce stock availability when adding to cart (soft check — hard check at order time).
- Delegate all storage to CartRepository.
"""

from __future__ import annotations

from app.repositories.cart_repository import CartRepository
from app.repositories.product_repository import ProductRepository
from app.schemas.cart import CartItemAdd, CartItemUpdate, CartResponse
from app.core.exceptions import InactiveProductException, InsufficientStockException
from app.core.logging import get_logger

logger = get_logger(__name__)


class CartService:

    def __init__(self, cart_repo: CartRepository, product_repo: ProductRepository) -> None:
        self._cart = cart_repo
        self._prod = product_repo

    @staticmethod
    def _to_response(doc: dict) -> CartResponse:
        return CartResponse.model_validate(doc)

    async def get_cart(self, user_id: str) -> CartResponse:
        """Get the user's cart. Creates an empty cart if none exists."""
        doc = await self._cart.get_or_create(user_id)
        return self._to_response(doc)

    async def add_item(self, user_id: str, data: CartItemAdd) -> CartResponse:
        """
        Add a product to the cart (or replace its quantity if already present).

        Business rules:
        1. Product must exist.
        2. Product must be active (status == 'active').
        3. Sufficient stock must be available (soft check).
        4. Price is snapshotted from the current product.final_price.

        If the product is already in the cart, the quantity is replaced (not added).
        This matches most e-commerce UX where "add to cart" with qty=2 means
        "I want 2", not "add 2 more".
        """
        # Ensure cart exists
        await self._cart.get_or_create(user_id)

        # Validate product
        product = await self._prod.find_by_id(data.product_id)

        if product.get("status") != "active":
            raise InactiveProductException(
                f"Product '{product.get('name')}' is not available for purchase.",
                detail={"product_id": data.product_id, "status": product.get("status")},
            )

        if product.get("stock_quantity", 0) < data.quantity:
            raise InsufficientStockException(
                f"Insufficient stock. Requested: {data.quantity}, available: {product.get('stock_quantity', 0)}.",
                detail={
                    "product_id": data.product_id,
                    "requested": data.quantity,
                    "available": product.get("stock_quantity", 0),
                },
            )

        unit_price = product.get("final_price", product["price"])
        images = product.get("image_urls", [])
        image_url = images[0] if images else None
        item_doc = {
            "product_id": data.product_id,
            "sku": product["sku"],
            "name": product["name"],
            "quantity": data.quantity,
            "unit_price": unit_price,
            "subtotal": round(unit_price * data.quantity, 2),
            "image_url": image_url,
        }

        doc = await self._cart.upsert_item(user_id, item_doc)
        return self._to_response(doc)

    async def update_item(
        self, user_id: str, product_id: str, data: CartItemUpdate
    ) -> CartResponse:
        """
        Update the quantity of an item already in the cart.

        Raises CartNotFoundException if the item is not in the cart.
        Re-validates stock for the new quantity.
        """
        product = await self._prod.find_by_id(product_id)

        if product.get("stock_quantity", 0) < data.quantity:
            raise InsufficientStockException(
                f"Insufficient stock. Requested: {data.quantity}, available: {product.get('stock_quantity', 0)}.",
                detail={"product_id": product_id, "requested": data.quantity},
            )

        unit_price = product.get("final_price", product["price"])
        doc = await self._cart.update_item_quantity(
            user_id, product_id, data.quantity, unit_price
        )
        return self._to_response(doc)

    async def remove_item(self, user_id: str, product_id: str) -> CartResponse:
        """Remove a single item from the cart."""
        doc = await self._cart.remove_item(user_id, product_id)
        return self._to_response(doc)

    async def clear_cart(self, user_id: str) -> CartResponse:
        """Remove all items from the cart."""
        doc = await self._cart.clear_cart(user_id)
        return self._to_response(doc)


def get_cart_service(
    cart_repo: CartRepository, product_repo: ProductRepository
) -> CartService:
    return CartService(cart_repo, product_repo)
