"""
app/api/routes/cart.py

Shopping cart endpoints.

User identity comes from the X-User-ID header (no auth in Stage 5).
All cart operations are scoped to the user making the request.

Endpoints:
  GET    /cart                          → get current cart
  POST   /cart/items                    → add item (or replace quantity)
  PUT    /cart/items/{product_id}       → update item quantity
  DELETE /cart/items/{product_id}       → remove single item
  DELETE /cart                          → clear entire cart
"""

from fastapi import APIRouter, Depends, Header, status
from pymongo.asynchronous.database import AsyncDatabase

from app.db.client import get_database
from app.repositories.cart_repository import CartRepository, get_cart_repository
from app.repositories.product_repository import ProductRepository, get_product_repository
from app.services.cart_service import CartService, get_cart_service
from app.schemas.cart import CartItemAdd, CartItemUpdate, CartResponse
from app.core.exceptions import ValidationException

router = APIRouter()


# ── Dependency wiring ─────────────────────────────────────────────────────────

def _cart_repo(db: AsyncDatabase = Depends(get_database)) -> CartRepository:
    return get_cart_repository(db)


def _prod_repo(db: AsyncDatabase = Depends(get_database)) -> ProductRepository:
    return get_product_repository(db)


def _service(
    cart_repo: CartRepository = Depends(_cart_repo),
    prod_repo: ProductRepository = Depends(_prod_repo),
) -> CartService:
    return get_cart_service(cart_repo, prod_repo)


def _user_id(x_user_id: str = Header(..., description="User identifier (e.g. 'user-123')")) -> str:
    """
    Extract user_id from the X-User-ID HTTP header.

    In Stage 7 (Authentication), this dependency will be replaced by JWT
    token parsing. Using a header dependency now means zero route handler
    changes will be needed when auth is added.
    """
    if not x_user_id or not x_user_id.strip():
        raise ValidationException("X-User-ID header is required.")
    return x_user_id.strip()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get(
    "/",
    summary="Get Cart",
    description="Get the current user's shopping cart. Creates an empty cart if none exists.",
    response_model=CartResponse,
)
async def get_cart(
    user_id: str = Depends(_user_id),
    service: CartService = Depends(_service),
) -> CartResponse:
    return await service.get_cart(user_id)


@router.post(
    "/items",
    summary="Add Item to Cart",
    description=(
        "Add a product to the cart. If the product is already in the cart, "
        "its quantity is replaced with the new value. "
        "Product must be active and have sufficient stock."
    ),
    response_model=CartResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Cart updated."},
        404: {"description": "Product not found."},
        422: {"description": "Product inactive or insufficient stock."},
    },
)
async def add_item(
    body: CartItemAdd,
    user_id: str = Depends(_user_id),
    service: CartService = Depends(_service),
) -> CartResponse:
    return await service.add_item(user_id, body)


@router.put(
    "/items/{product_id}",
    summary="Update Cart Item",
    description="Update the quantity of an item already in the cart.",
    response_model=CartResponse,
    responses={
        200: {"description": "Cart updated."},
        404: {"description": "Item not in cart."},
        422: {"description": "Insufficient stock."},
    },
)
async def update_item(
    product_id: str,
    body: CartItemUpdate,
    user_id: str = Depends(_user_id),
    service: CartService = Depends(_service),
) -> CartResponse:
    return await service.update_item(user_id, product_id, body)


@router.delete(
    "/items/{product_id}",
    summary="Remove Cart Item",
    description="Remove a single item from the cart.",
    response_model=CartResponse,
    responses={
        200: {"description": "Cart updated."},
        404: {"description": "Item not in cart."},
    },
)
async def remove_item(
    product_id: str,
    user_id: str = Depends(_user_id),
    service: CartService = Depends(_service),
) -> CartResponse:
    return await service.remove_item(user_id, product_id)


@router.delete(
    "/",
    summary="Clear Cart",
    description="Remove all items from the cart.",
    response_model=CartResponse,
)
async def clear_cart(
    user_id: str = Depends(_user_id),
    service: CartService = Depends(_service),
) -> CartResponse:
    return await service.clear_cart(user_id)
