"""
app/api/routes/products.py

HTTP route handlers for the product catalog.

This layer is intentionally thin:
- Parse and validate the HTTP request (FastAPI + Pydantic handle this).
- Call the service with validated data.
- Return the appropriate HTTP status code and response schema.

No business logic lives here. If you find yourself writing an if/else
that makes a domain decision (not an HTTP decision) inside a route handler,
that logic belongs in the service layer.

Dependency chain per request:
  FastAPI resolves: db = get_database()
                    repo = get_product_repository(db)
                    service = get_product_service(repo)
  Route handler receives: service, pagination, ...
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from pymongo.asynchronous.database import AsyncDatabase

from app.db.client import get_database
from app.repositories.product_repository import ProductRepository, get_product_repository
from app.services.product_service import ProductService, get_product_service
from app.schemas.product import (
    ProductCreate,
    ProductListItem,
    ProductResponse,
    ProductStatus,
    ProductUpdate,
)
from app.schemas.common import PaginatedResponse

router = APIRouter()


# ── Dependency wiring ─────────────────────────────────────────────────────────

def _repo(db: AsyncDatabase = Depends(get_database)) -> ProductRepository:
    return get_product_repository(db)


def _service(repo: ProductRepository = Depends(_repo)) -> ProductService:
    return get_product_service(repo)


# ── POST /products ─────────────────────────────────────────────────────────────

@router.post(
    "/",
    summary="Create Product",
    description="Add a new product to the catalog. SKU must be unique.",
    status_code=status.HTTP_201_CREATED,
    response_model=ProductResponse,
    responses={
        201: {"description": "Product created successfully."},
        409: {"description": "A product with this SKU already exists."},
        422: {"description": "Validation error in request body."},
    },
)
async def create_product(
    body: ProductCreate,
    service: ProductService = Depends(_service),
) -> ProductResponse:
    return await service.create_product(body)


# ── GET /products ──────────────────────────────────────────────────────────────

@router.get(
    "/",
    summary="List Products",
    description=(
        "Paginated product catalog with optional filtering and sorting. "
        "Price filters apply to the discounted final_price."
    ),
    response_model=PaginatedResponse[ProductListItem],
    responses={
        200: {"description": "Paginated list of products."},
    },
)
async def list_products(
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    limit: int = Query(default=20, ge=1, le=100, description="Items per page"),
    category: Optional[str] = Query(default=None, description="Filter by category"),
    brand: Optional[str] = Query(default=None, description="Filter by brand"),
    min_price: Optional[float] = Query(default=None, ge=0, description="Minimum final price"),
    max_price: Optional[float] = Query(default=None, ge=0, description="Maximum final price"),
    status: Optional[ProductStatus] = Query(default=None, description="Filter by status"),
    sort_by: str = Query(
        default="created_at",
        description="Sort field: price | name | created_at | brand | discount_percentage",
    ),
    sort_order: str = Query(default="desc", description="Sort direction: asc | desc"),
    service: ProductService = Depends(_service),
) -> PaginatedResponse[ProductListItem]:
    return await service.list_products(
        page=page,
        limit=limit,
        category=category,
        brand=brand,
        min_price=min_price,
        max_price=max_price,
        status=status.value if status else None,
        sort_by=sort_by,
        sort_order=sort_order,
    )


# ── GET /products/{product_id} ─────────────────────────────────────────────────

@router.get(
    "/{product_id}",
    summary="Get Product",
    description="Retrieve a single product by its MongoDB ObjectId.",
    response_model=ProductResponse,
    responses={
        200: {"description": "Product found."},
        404: {"description": "Product not found."},
    },
)
async def get_product(
    product_id: str,
    service: ProductService = Depends(_service),
) -> ProductResponse:
    return await service.get_product(product_id)


# ── PUT /products/{product_id} ─────────────────────────────────────────────────

@router.put(
    "/{product_id}",
    summary="Update Product",
    description=(
        "Partial update — send only the fields you want to change. "
        "SKU cannot be changed after creation. "
        "final_price is recomputed automatically when price or discount changes."
    ),
    response_model=ProductResponse,
    responses={
        200: {"description": "Product updated."},
        404: {"description": "Product not found."},
        422: {"description": "Validation error in request body."},
    },
)
async def update_product(
    product_id: str,
    body: ProductUpdate,
    service: ProductService = Depends(_service),
) -> ProductResponse:
    return await service.update_product(product_id, body)


# ── DELETE /products/{product_id} ─────────────────────────────────────────────

@router.delete(
    "/{product_id}",
    summary="Delete Product",
    description="Permanently delete a product from the catalog.",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        204: {"description": "Product deleted."},
        404: {"description": "Product not found."},
    },
)
async def delete_product(
    product_id: str,
    service: ProductService = Depends(_service),
) -> None:
    await service.delete_product(product_id)
