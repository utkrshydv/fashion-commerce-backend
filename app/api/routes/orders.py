"""
app/api/routes/orders.py

Order management endpoints.

All endpoints require the X-User-ID header for user identity.

Endpoints:
  POST /orders                 → place order from cart
  GET  /orders                 → list user's orders (paginated)
  GET  /orders/{id}            → get single order (ownership enforced)
  PUT  /orders/{id}/status     → advance order status (state machine)
"""

from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, status
from pymongo.asynchronous.database import AsyncDatabase

from app.db.client import get_database
from app.repositories.cart_repository import CartRepository, get_cart_repository
from app.repositories.inventory_repository import InventoryRepository, get_inventory_repository
from app.repositories.order_repository import OrderRepository, get_order_repository
from app.services.order_service import OrderService, get_order_service
from app.schemas.order import (
    OrderCreate,
    OrderListItem,
    OrderResponse,
    OrderStatus,
    OrderStatusUpdate,
)
from app.schemas.common import PaginatedResponse
from app.core.exceptions import ValidationException

router = APIRouter()


# ── Dependency wiring ─────────────────────────────────────────────────────────

def _order_repo(db: AsyncDatabase = Depends(get_database)) -> OrderRepository:
    return get_order_repository(db)


def _cart_repo(db: AsyncDatabase = Depends(get_database)) -> CartRepository:
    return get_cart_repository(db)


def _inv_repo(db: AsyncDatabase = Depends(get_database)) -> InventoryRepository:
    return get_inventory_repository(db)


def _service(
    order_repo: OrderRepository = Depends(_order_repo),
    cart_repo: CartRepository = Depends(_cart_repo),
    inv_repo: InventoryRepository = Depends(_inv_repo),
) -> OrderService:
    return get_order_service(order_repo, cart_repo, inv_repo)


def _user_id(x_user_id: str = Header(...)) -> str:
    if not x_user_id or not x_user_id.strip():
        raise ValidationException("X-User-ID header is required.")
    return x_user_id.strip()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/",
    summary="Place Order",
    description=(
        "Convert the user's cart into an order. "
        "Validates stock for all items, deducts inventory, and clears the cart. "
        "Cart must not be empty."
    ),
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "Order placed successfully."},
        400: {"description": "Cart is empty."},
        422: {"description": "Insufficient stock for one or more items."},
    },
)
async def place_order(
    body: OrderCreate,
    user_id: str = Depends(_user_id),
    service: OrderService = Depends(_service),
) -> OrderResponse:
    return await service.place_order(user_id, body)


@router.get(
    "/",
    summary="List Orders",
    description="Get the current user's orders, newest first. Supports status filtering.",
    response_model=PaginatedResponse[OrderListItem],
)
async def list_orders(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    status: Optional[OrderStatus] = Query(default=None, description="Filter by status"),
    user_id: str = Depends(_user_id),
    service: OrderService = Depends(_service),
) -> PaginatedResponse[OrderListItem]:
    return await service.list_orders(
        user_id=user_id,
        page=page,
        limit=limit,
        status_filter=status.value if status else None,
    )


@router.get(
    "/{order_id}",
    summary="Get Order",
    description="Get a single order by ID. Returns 404 if not found or not owned by you.",
    response_model=OrderResponse,
    responses={
        200: {"description": "Order found."},
        404: {"description": "Order not found."},
    },
)
async def get_order(
    order_id: str,
    user_id: str = Depends(_user_id),
    service: OrderService = Depends(_service),
) -> OrderResponse:
    return await service.get_order(user_id, order_id)


@router.put(
    "/{order_id}/status",
    summary="Update Order Status",
    description=(
        "Advance the order through the status state machine. "
        "Valid transitions: pending→confirmed, pending→cancelled, "
        "confirmed→shipped, confirmed→cancelled, shipped→delivered."
    ),
    response_model=OrderResponse,
    responses={
        200: {"description": "Status updated."},
        400: {"description": "Invalid status transition."},
        404: {"description": "Order not found."},
    },
)
async def update_order_status(
    order_id: str,
    body: OrderStatusUpdate,
    user_id: str = Depends(_user_id),
    service: OrderService = Depends(_service),
) -> OrderResponse:
    return await service.update_order_status(user_id, order_id, body)
