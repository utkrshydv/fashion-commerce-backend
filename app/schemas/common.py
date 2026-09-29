"""
app/schemas/common.py

Shared Pydantic schemas reused across multiple domain modules.

Includes:
- PyObjectId: coerces MongoDB ObjectId strings for use in Pydantic v2 models
- PaginationParams: validated query parameters for paginated list endpoints
- PaginatedResponse: generic wrapper for paginated API responses
"""

from __future__ import annotations

from typing import Any, Generic, List, TypeVar
from pydantic import BaseModel, Field, field_validator


# ── ObjectId handling ─────────────────────────────────────────────────────────

class PyObjectId(str):
    """
    A str subclass that validates MongoDB ObjectId format.

    MongoDB stores documents with `_id: ObjectId(...)` internally.
    The API exposes them as plain 24-character hex strings.

    Usage in a Pydantic model:
        id: PyObjectId = Field(alias="_id")

    Why not use bson.ObjectId directly?
    - bson.ObjectId is not JSON-serializable by default.
    - Pydantic v2 doesn't know how to validate it.
    - A plain str that validates the format gives us full JSON serialization
      with zero extra configuration.
    """

    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v: Any, _info: Any = None) -> str:
        if isinstance(v, str) and len(v) == 24:
            return v
        # bson.ObjectId instances have a str representation
        s = str(v)
        if len(s) == 24:
            return s
        raise ValueError(f"Invalid ObjectId: {v!r}")

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: Any) -> Any:
        from pydantic_core import core_schema
        return core_schema.no_info_plain_validator_function(
            cls.validate,
            serialization=core_schema.to_string_ser_schema(),
        )


# ── Pagination ────────────────────────────────────────────────────────────────

class PaginationParams(BaseModel):
    """
    Validated pagination query parameters.

    Used as a FastAPI dependency:
        async def list_products(pagination: PaginationParams = Depends()):
            skip = pagination.skip
            limit = pagination.limit
    """
    page: int = Field(default=1, ge=1, description="Page number (1-indexed)")
    limit: int = Field(default=20, ge=1, le=100, description="Items per page (max 100)")

    @property
    def skip(self) -> int:
        """Number of documents to skip for this page."""
        return (self.page - 1) * self.limit


T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """
    Generic paginated API response wrapper.

    Example response:
    {
        "items": [...],
        "total": 150,
        "page": 2,
        "limit": 20,
        "pages": 8
    }
    """
    items: List[T]
    total: int
    page: int
    limit: int
    pages: int

    @classmethod
    def build(
        cls,
        items: List[T],
        total: int,
        page: int,
        limit: int,
    ) -> "PaginatedResponse[T]":
        """Factory method to calculate pages automatically."""
        import math
        return cls(
            items=items,
            total=total,
            page=page,
            limit=limit,
            pages=math.ceil(total / limit) if limit > 0 else 0,
        )
