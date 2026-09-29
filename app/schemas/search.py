"""
app/schemas/search.py

Pydantic schemas for the search domain.

Search is intentionally a separate schema namespace from product listing.
The list endpoint returns catalog browsing (filtered, sorted); the search
endpoint returns relevance-ranked results with a text-match score.

SearchResult extends ProductListItem with a `score` field (MongoDB text
search relevance score) so the client can see how well each item matched.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from app.schemas.product import ProductListItem
from app.schemas.common import PaginatedResponse


class SearchResult(ProductListItem):
    """
    A product in a search results list.

    Adds `score` — the MongoDB text search relevance score.
    Higher score = better match.

    score is optional (None) when the search is filter-only with no query string.
    """
    score: Optional[float] = Field(
        default=None,
        description="MongoDB text search relevance score. Higher = better match.",
    )


class SearchResponse(BaseModel):
    """
    Response body for GET /search.

    Wraps search results with pagination metadata and echoes the query
    back so clients know what was searched.
    """
    query: Optional[str] = Field(None, description="The search query string, if any.")
    items: List[SearchResult]
    total: int
    page: int
    limit: int
    pages: int

    @classmethod
    def build(
        cls,
        items: List[SearchResult],
        total: int,
        page: int,
        limit: int,
        query: Optional[str] = None,
    ) -> "SearchResponse":
        import math
        return cls(
            query=query,
            items=items,
            total=total,
            page=page,
            limit=limit,
            pages=math.ceil(total / limit) if total > 0 else 0,
        )
