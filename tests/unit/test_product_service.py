"""
tests/unit/test_product_service.py

Unit tests for ProductService business logic.

What we test here:
- final_price computation (the most important business rule)
- Validation rules that live in the schema (price, discount, required fields)
- Status enum values
- PaginatedResponse.build() page calculation

What we do NOT test here:
- Database operations (that's ProductRepository, covered in integration tests)
- HTTP status codes (that's the router layer)

These tests run in milliseconds — no database or HTTP stack required.
"""

import math
import pytest
from app.services.product_service import ProductService
from app.schemas.product import ProductCreate, ProductUpdate, ProductStatus
from app.schemas.common import PaginatedResponse, PaginationParams


class TestFinalPriceComputation:
    """Tests for ProductService._compute_final_price()"""

    def test_no_discount_returns_full_price(self) -> None:
        result = ProductService._compute_final_price(1000.0, 0.0)
        assert result == 1000.0

    def test_10_percent_discount(self) -> None:
        result = ProductService._compute_final_price(1000.0, 10.0)
        assert result == 900.0

    def test_50_percent_discount(self) -> None:
        result = ProductService._compute_final_price(2000.0, 50.0)
        assert result == 1000.0

    def test_90_percent_discount_maximum_allowed(self) -> None:
        result = ProductService._compute_final_price(500.0, 90.0)
        assert result == 50.0

    def test_floating_point_result_is_rounded(self) -> None:
        # 999 * (1 - 10/100) = 999 * 0.9 = 899.1
        result = ProductService._compute_final_price(999.0, 10.0)
        assert result == 899.1

    def test_zero_price_with_any_discount_is_zero(self) -> None:
        result = ProductService._compute_final_price(0.0, 50.0)
        assert result == 0.0

    def test_result_is_float(self) -> None:
        result = ProductService._compute_final_price(100.0, 0.0)
        assert isinstance(result, float)

    def test_fractional_discount(self) -> None:
        # 1000 * (1 - 7.5/100) = 925.0
        result = ProductService._compute_final_price(1000.0, 7.5)
        assert result == 925.0


class TestProductCreateValidation:
    """Schema-level validation tests for ProductCreate."""

    def _valid_payload(self, **overrides) -> dict:
        base = {
            "sku": "SHIRT-001",
            "name": "Classic White Shirt",
            "brand": "Arrow",
            "category": "Men",
            "price": 999.0,
            "discount_percentage": 10.0,
            "stock_quantity": 50,
            "description": "A crisp white formal shirt.",
            "available_sizes": ["S", "M", "L", "XL"],
            "available_colors": ["White"],
            "image_urls": [],
        }
        base.update(overrides)
        return base

    def test_valid_product_creates_successfully(self) -> None:
        data = ProductCreate(**self._valid_payload())
        assert data.name == "Classic White Shirt"
        assert data.sku == "SHIRT-001"  # uppercase normalised

    def test_sku_is_normalised_to_uppercase(self) -> None:
        data = ProductCreate(**self._valid_payload(sku="shirt-001"))
        assert data.sku == "SHIRT-001"

    def test_sku_normalised_strips_whitespace(self) -> None:
        data = ProductCreate(**self._valid_payload(sku="  SHIRT-001  "))
        assert data.sku == "SHIRT-001"

    def test_negative_price_raises(self) -> None:
        with pytest.raises(Exception):
            ProductCreate(**self._valid_payload(price=-1.0))

    def test_zero_price_is_valid(self) -> None:
        data = ProductCreate(**self._valid_payload(price=0.0))
        assert data.price == 0.0

    def test_discount_above_90_raises(self) -> None:
        with pytest.raises(Exception):
            ProductCreate(**self._valid_payload(discount_percentage=91.0))

    def test_discount_exactly_90_is_valid(self) -> None:
        data = ProductCreate(**self._valid_payload(discount_percentage=90.0))
        assert data.discount_percentage == 90.0

    def test_discount_below_0_raises(self) -> None:
        with pytest.raises(Exception):
            ProductCreate(**self._valid_payload(discount_percentage=-1.0))

    def test_negative_stock_raises(self) -> None:
        with pytest.raises(Exception):
            ProductCreate(**self._valid_payload(stock_quantity=-1))

    def test_zero_stock_is_valid(self) -> None:
        data = ProductCreate(**self._valid_payload(stock_quantity=0))
        assert data.stock_quantity == 0

    def test_missing_name_raises(self) -> None:
        payload = self._valid_payload()
        del payload["name"]
        with pytest.raises(Exception):
            ProductCreate(**payload)

    def test_missing_sku_raises(self) -> None:
        payload = self._valid_payload()
        del payload["sku"]
        with pytest.raises(Exception):
            ProductCreate(**payload)

    def test_missing_brand_raises(self) -> None:
        payload = self._valid_payload()
        del payload["brand"]
        with pytest.raises(Exception):
            ProductCreate(**payload)

    def test_default_status_is_active(self) -> None:
        data = ProductCreate(**self._valid_payload())
        assert data.status == ProductStatus.ACTIVE

    def test_empty_name_raises(self) -> None:
        with pytest.raises(Exception):
            ProductCreate(**self._valid_payload(name=""))


class TestProductUpdateValidation:
    """Validation tests for ProductUpdate (all-optional partial schema)."""

    def test_empty_update_is_valid(self) -> None:
        """ProductUpdate with no fields is valid — means 'no changes'."""
        data = ProductUpdate()
        dumped = data.model_dump(exclude_none=True)
        assert dumped == {}

    def test_price_only_update_is_valid(self) -> None:
        data = ProductUpdate(price=1500.0)
        dumped = data.model_dump(exclude_none=True)
        assert dumped == {"price": 1500.0}

    def test_status_only_update_is_valid(self) -> None:
        data = ProductUpdate(status=ProductStatus.INACTIVE)
        dumped = data.model_dump(exclude_none=True)
        assert dumped["status"] == ProductStatus.INACTIVE

    def test_negative_price_in_update_raises(self) -> None:
        with pytest.raises(Exception):
            ProductUpdate(price=-100.0)

    def test_discount_above_90_in_update_raises(self) -> None:
        with pytest.raises(Exception):
            ProductUpdate(discount_percentage=95.0)


class TestProductStatus:
    """Enum value tests."""

    def test_active_value(self) -> None:
        assert ProductStatus.ACTIVE.value == "active"

    def test_inactive_value(self) -> None:
        assert ProductStatus.INACTIVE.value == "inactive"

    def test_out_of_stock_value(self) -> None:
        assert ProductStatus.OUT_OF_STOCK.value == "out_of_stock"


class TestPaginationParams:
    """Tests for shared PaginationParams schema."""

    def test_default_page_is_1(self) -> None:
        p = PaginationParams()
        assert p.page == 1

    def test_default_limit_is_20(self) -> None:
        p = PaginationParams()
        assert p.limit == 20

    def test_skip_calculation_page_1(self) -> None:
        p = PaginationParams(page=1, limit=20)
        assert p.skip == 0

    def test_skip_calculation_page_2(self) -> None:
        p = PaginationParams(page=2, limit=20)
        assert p.skip == 20

    def test_skip_calculation_page_3_limit_10(self) -> None:
        p = PaginationParams(page=3, limit=10)
        assert p.skip == 20

    def test_page_below_1_raises(self) -> None:
        with pytest.raises(Exception):
            PaginationParams(page=0)

    def test_limit_above_100_raises(self) -> None:
        with pytest.raises(Exception):
            PaginationParams(limit=101)


class TestPaginatedResponse:
    """Tests for PaginatedResponse.build() page count calculation."""

    def test_exact_pages(self) -> None:
        r = PaginatedResponse.build(items=[], total=40, page=1, limit=20)
        assert r.pages == 2

    def test_partial_last_page(self) -> None:
        r = PaginatedResponse.build(items=[], total=41, page=1, limit=20)
        assert r.pages == 3

    def test_zero_total(self) -> None:
        r = PaginatedResponse.build(items=[], total=0, page=1, limit=20)
        assert r.pages == 0

    def test_single_item(self) -> None:
        r = PaginatedResponse.build(items=["x"], total=1, page=1, limit=20)
        assert r.pages == 1
        assert r.total == 1

    def test_metadata_preserved(self) -> None:
        r = PaginatedResponse.build(items=[], total=100, page=3, limit=10)
        assert r.page == 3
        assert r.limit == 10
        assert r.total == 100
        assert r.pages == 10
