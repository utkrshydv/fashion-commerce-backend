"""
app/api/routes/search.py

Search endpoint for the product catalog.

GET /search?q=<text>&category=&min_price=&max_price=&page=&limit=

Why a separate /search route instead of /products?q=...?
- The response schema is different: SearchResult includes a relevance `score`.
- The sort is fixed to relevance (not configurable like /products sort).
- The semantics are different: /products is "show me the catalog", /search
  is "show me what best matches this query".
- Keeping them separate makes the API intent explicit and the OpenAPI docs cleaner.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from pymongo.asynchronous.database import AsyncDatabase

from app.db.client import get_database
from app.repositories.product_repository import ProductRepository, get_product_repository
from app.services.product_service import ProductService, get_product_service
from app.schemas.search import SearchResponse

router = APIRouter()


def _repo(db: AsyncDatabase = Depends(get_database)) -> ProductRepository:
    return get_product_repository(db)


def _service(repo: ProductRepository = Depends(_repo)) -> ProductService:
    return get_product_service(repo)


@router.get(
    "/",
    summary="Search Products",
    description=(
        "Full-text search across product name, description, and brand. "
        "Results are ranked by relevance score (best match first). "
        "Supports additional filters: category, price range."
    ),
    response_model=SearchResponse,
    responses={
        200: {"description": "Search results with relevance scores."},
        422: {"description": "Query too short (minimum 2 characters)."},
    },
)
async def search_products(
    q: str = Query(..., min_length=2, description="Search query (minimum 2 characters)"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    category: Optional[str] = Query(default=None),
    min_price: Optional[float] = Query(default=None, ge=0),
    max_price: Optional[float] = Query(default=None, ge=0),
    service: ProductService = Depends(_service),
) -> SearchResponse:
    return await service.search_products(
        query=q,
        page=page,
        limit=limit,
        category=category,
        min_price=min_price,
        max_price=max_price,
    )
