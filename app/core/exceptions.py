"""
app/core/exceptions.py

Custom exception hierarchy for the application.

Strategy:
- Define a base AppException carrying an HTTP status code and a
  machine-readable error code. This lets the global exception handler
  in main.py convert any AppException to a consistent JSON response
  without scattering HTTPException raises across the business logic.
- Route handlers and services raise these domain exceptions.
- The global handler translates them to HTTP responses.
- MongoDB/driver exceptions are caught at the repository layer and
  re-raised as AppException subclasses so callers never see raw
  pymongo errors.
"""

from typing import Any


class AppException(Exception):
    """
    Base class for all application-defined exceptions.

    Attributes:
        status_code: HTTP status code to return to the client.
        error_code:  Machine-readable string (useful for frontend error handling).
        message:     Human-readable description.
        detail:      Optional extra context (e.g. field names, attempted value).
    """

    status_code: int = 500
    error_code: str = "internal_error"

    def __init__(self, message: str, detail: Any = None) -> None:
        self.message = message
        self.detail = detail
        super().__init__(message)


# ── 400 Bad Request ───────────────────────────────────────────────────────────

class ValidationException(AppException):
    """Input failed business-rule validation (distinct from Pydantic schema validation)."""
    status_code = 400
    error_code = "validation_error"


class InvalidQuantityException(AppException):
    """Quantity is zero, negative, or exceeds allowed maximum."""
    status_code = 400
    error_code = "invalid_quantity"


class InvalidStatusTransitionException(AppException):
    """Order status cannot move from current state to requested state."""
    status_code = 400
    error_code = "invalid_status_transition"


# ── 404 Not Found ─────────────────────────────────────────────────────────────

class NotFoundException(AppException):
    """Generic resource not found."""
    status_code = 404
    error_code = "not_found"


class ProductNotFoundException(NotFoundException):
    error_code = "product_not_found"


class CartNotFoundException(NotFoundException):
    error_code = "cart_not_found"


class OrderNotFoundException(NotFoundException):
    error_code = "order_not_found"


class InventoryNotFoundException(NotFoundException):
    error_code = "inventory_not_found"


# ── 409 Conflict ──────────────────────────────────────────────────────────────

class DuplicateSKUException(AppException):
    """A product with this SKU already exists."""
    status_code = 409
    error_code = "duplicate_sku"


# ── 422 Unprocessable ─────────────────────────────────────────────────────────

class InsufficientStockException(AppException):
    """Requested quantity exceeds available stock."""
    status_code = 422
    error_code = "insufficient_stock"


class InactiveProductException(AppException):
    """Cannot add an inactive product to the cart."""
    status_code = 422
    error_code = "inactive_product"


# ── 500 Internal ──────────────────────────────────────────────────────────────

class DatabaseException(AppException):
    """Wraps unexpected MongoDB/driver errors."""
    status_code = 500
    error_code = "database_error"
