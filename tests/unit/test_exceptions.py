"""
tests/unit/test_exceptions.py

Unit tests for the custom exception hierarchy in app/core/exceptions.py.

These tests require no database or HTTP stack — they validate that:
- Exception subclasses carry the correct HTTP status codes and error codes.
- The AppException base class stores message and detail correctly.
- Exception instances are proper subclasses (important for the global handler).
"""

import pytest

from app.core.exceptions import (
    AppException,
    ValidationException,
    InvalidQuantityException,
    InvalidStatusTransitionException,
    NotFoundException,
    ProductNotFoundException,
    CartNotFoundException,
    OrderNotFoundException,
    InventoryNotFoundException,
    DuplicateSKUException,
    InsufficientStockException,
    InactiveProductException,
    DatabaseException,
)


class TestAppExceptionBase:
    """Tests for the AppException base class."""

    def test_stores_message(self) -> None:
        exc = AppException("something went wrong")
        assert exc.message == "something went wrong"

    def test_stores_detail_none_by_default(self) -> None:
        exc = AppException("msg")
        assert exc.detail is None

    def test_stores_optional_detail(self) -> None:
        exc = AppException("msg", detail={"field": "sku", "value": "ABC"})
        assert exc.detail == {"field": "sku", "value": "ABC"}

    def test_is_exception_subclass(self) -> None:
        exc = AppException("msg")
        assert isinstance(exc, Exception)

    def test_str_representation(self) -> None:
        exc = AppException("test message")
        assert "test message" in str(exc)


class TestStatusCodes:
    """Verify every exception subclass carries the right HTTP status code."""

    @pytest.mark.parametrize("exc_class,expected_status", [
        (ValidationException,              400),
        (InvalidQuantityException,         400),
        (InvalidStatusTransitionException, 400),
        (NotFoundException,                404),
        (ProductNotFoundException,         404),
        (CartNotFoundException,            404),
        (OrderNotFoundException,           404),
        (InventoryNotFoundException,       404),
        (DuplicateSKUException,            409),
        (InsufficientStockException,       422),
        (InactiveProductException,         422),
        (DatabaseException,                500),
    ])
    def test_status_code(self, exc_class, expected_status) -> None:
        exc = exc_class("test")
        assert exc.status_code == expected_status, (
            f"{exc_class.__name__} has status_code={exc.status_code}, "
            f"expected {expected_status}"
        )


class TestErrorCodes:
    """Verify every exception subclass carries a machine-readable error code."""

    @pytest.mark.parametrize("exc_class,expected_code", [
        (ValidationException,              "validation_error"),
        (InvalidQuantityException,         "invalid_quantity"),
        (InvalidStatusTransitionException, "invalid_status_transition"),
        (NotFoundException,                "not_found"),
        (ProductNotFoundException,         "product_not_found"),
        (CartNotFoundException,            "cart_not_found"),
        (OrderNotFoundException,           "order_not_found"),
        (InventoryNotFoundException,       "inventory_not_found"),
        (DuplicateSKUException,            "duplicate_sku"),
        (InsufficientStockException,       "insufficient_stock"),
        (InactiveProductException,         "inactive_product"),
        (DatabaseException,                "database_error"),
    ])
    def test_error_code(self, exc_class, expected_code) -> None:
        exc = exc_class("test")
        assert exc.error_code == expected_code


class TestInheritanceHierarchy:
    """
    Verify the inheritance chain so the global exception handler in main.py
    can catch AppException and its subclasses with a single handler.
    """

    def test_product_not_found_is_not_found(self) -> None:
        assert issubclass(ProductNotFoundException, NotFoundException)

    def test_cart_not_found_is_not_found(self) -> None:
        assert issubclass(CartNotFoundException, NotFoundException)

    def test_order_not_found_is_not_found(self) -> None:
        assert issubclass(OrderNotFoundException, NotFoundException)

    def test_inventory_not_found_is_not_found(self) -> None:
        assert issubclass(InventoryNotFoundException, NotFoundException)

    def test_all_subclasses_are_app_exceptions(self) -> None:
        subclasses = [
            ValidationException, InvalidQuantityException,
            InvalidStatusTransitionException, NotFoundException,
            ProductNotFoundException, CartNotFoundException,
            OrderNotFoundException, InventoryNotFoundException,
            DuplicateSKUException, InsufficientStockException,
            InactiveProductException, DatabaseException,
        ]
        for cls in subclasses:
            assert issubclass(cls, AppException), (
                f"{cls.__name__} is not a subclass of AppException"
            )
