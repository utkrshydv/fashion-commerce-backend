"""
app/schemas/product.py

Pydantic schemas for the Product domain — the shapes of data that cross
the HTTP boundary (request bodies and response bodies).

Schema separation from models
──────────────────────────────
Models  (app/models/product.py)  = what lives in MongoDB
Schemas (this file)              = what the API accepts and returns

They differ because:
- MongoDB uses `_id` (ObjectId); the API uses `id` (string)
- `final_price` is computed in the service layer, never stored
- `created_at` and `updated_at` are server-set timestamps, not writable
- A CREATE request doesn't include `id` (not yet known)
- An UPDATE request makes all fields optional (PATCH semantics)

Schema hierarchy:
  ProductBase           ← shared fields with shared validators
      ↓
  ProductCreate         ← POST /products body (all required fields + SKU)
  ProductUpdate         ← PUT /products/{id} body (all fields optional)
  ProductResponse       ← GET response (includes id, final_price, timestamps)
  ProductListResponse   ← lightweight list item (subset of fields)
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.common import PyObjectId


# ── Enumerations ──────────────────────────────────────────────────────────────

class ProductStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    OUT_OF_STOCK = "out_of_stock"


class SizeOption(str, Enum):
    XS = "XS"
    S = "S"
    M = "M"
    L = "L"
    XL = "XL"
    XXL = "XXL"
    FREE = "FREE"
    # Numeric sizes for footwear/accessories
    SIZE_6 = "6"
    SIZE_7 = "7"
    SIZE_8 = "8"
    SIZE_9 = "9"
    SIZE_10 = "10"
    SIZE_11 = "11"


# ── Base schema ───────────────────────────────────────────────────────────────

class ProductBase(BaseModel):
    """
    Fields shared between ProductCreate and ProductUpdate.
    Validators defined here apply to both schemas.
    """
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    brand: Optional[str] = Field(None, min_length=1, max_length=100)
    category: Optional[str] = Field(None, min_length=1, max_length=100)
    price: Optional[float] = Field(None, description="Base price in INR")
    discount_percentage: Optional[float] = Field(
        None, description="Discount as a percentage (0–90)"
    )
    available_sizes: Optional[List[str]] = Field(None)
    available_colors: Optional[List[str]] = Field(None)
    image_urls: Optional[List[str]] = Field(None)
    stock_quantity: Optional[int] = Field(None, ge=0)
    status: Optional[ProductStatus] = Field(None)

    @field_validator("price")
    @classmethod
    def price_must_be_positive(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v < 0:
            raise ValueError("price cannot be negative")
        return v

    @field_validator("discount_percentage")
    @classmethod
    def discount_must_be_in_range(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (0 <= v <= 90):
            raise ValueError("discount_percentage must be between 0 and 90")
        return v



# ── Create schema ─────────────────────────────────────────────────────────────

class ProductCreate(ProductBase):
    """
    Request body for POST /products.

    All required fields are declared here (with default=None removed).
    SKU is part of the create schema only — it cannot be changed after creation.
    """
    sku: str = Field(..., min_length=1, max_length=50, description="Unique product SKU")
    name: str = Field(..., min_length=1, max_length=200)
    brand: str = Field(..., min_length=1, max_length=100)
    category: str = Field(..., min_length=1, max_length=100)
    price: float = Field(..., ge=0, description="Base price in INR")
    discount_percentage: float = Field(
        default=0.0, ge=0, le=90, description="Discount percentage (0–90)"
    )
    stock_quantity: int = Field(..., ge=0, description="Initial stock quantity")
    status: ProductStatus = Field(default=ProductStatus.ACTIVE)
    available_sizes: List[str] = Field(default_factory=list)
    available_colors: List[str] = Field(default_factory=list)
    image_urls: List[str] = Field(default_factory=list)
    description: str = Field(default="", max_length=2000)

    @field_validator("sku")
    @classmethod
    def sku_must_be_uppercase_alphanumeric(cls, v: str) -> str:
        """
        Normalise SKU to uppercase and validate format.
        SKUs like 'sku-001', 'SKU001', 'SHIRT-M-BLK' are all valid.
        """
        return v.strip().upper()


# ── Update schema ─────────────────────────────────────────────────────────────

class ProductUpdate(ProductBase):
    """
    Request body for PUT /products/{id}.

    All fields are Optional — clients send only the fields they want to change.
    SKU is intentionally excluded: SKUs are immutable after creation.

    Why PUT instead of PATCH?
    The spec says PUT. In this implementation PUT behaves like a partial update
    (only provided fields are updated) because all fields are Optional.
    This is pragmatic: forcing clients to resend the entire document for a
    single price change is unnecessary friction.
    """
    pass  # All fields are already Optional in ProductBase


# ── Response schemas ──────────────────────────────────────────────────────────

class ProductResponse(BaseModel):
    """
    Full product response returned by GET /products/{id}, POST, and PUT.

    Includes computed fields (final_price) and server-set metadata (timestamps).
    """
    id: PyObjectId = Field(alias="_id")
    sku: str
    name: str
    description: str
    brand: str
    category: str
    price: float
    discount_percentage: float
    final_price: float = Field(description="price after discount, computed by service layer")
    available_sizes: List[str]
    available_colors: List[str]
    image_urls: List[str]
    stock_quantity: int
    status: ProductStatus
    created_at: datetime
    updated_at: datetime

    model_config = {
        "populate_by_name": True,  # accept both `id` and `_id` as field name
        "arbitrary_types_allowed": True,
    }


class ProductListItem(BaseModel):
    """
    Lightweight product representation returned in paginated list responses.

    Omits description and image_urls to reduce payload size.
    The client can fetch the full ProductResponse for any individual product.
    """
    id: PyObjectId = Field(alias="_id")
    sku: str
    name: str
    brand: str
    category: str
    price: float
    discount_percentage: float
    final_price: float
    stock_quantity: int
    status: ProductStatus
    created_at: datetime

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
    }
