"""
tests/integration/test_products.py

Integration tests for the product catalog API.

These tests exercise the full stack:
  HTTP request → FastAPI → ProductService → ProductRepository → MongoDB → response

Each test:
1. Gets a fresh AsyncClient (function scope).
2. Gets a real AsyncDatabase handle pointing at fashion_commerce_test.
3. Cleans up the products collection after itself.

Test categories:
- POST /products          : create, duplicate SKU, validation errors
- GET /products/{id}      : happy path, not found, bad ID
- GET /products           : pagination, filters, sort
- PUT /products/{id}      : partial update, final_price recomputation, not found
- DELETE /products/{id}   : happy path, not found
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from pymongo.asynchronous.database import AsyncDatabase


# ── Helpers ───────────────────────────────────────────────────────────────────

def _product_payload(**overrides) -> dict:
    """Return a valid ProductCreate payload, with optional overrides."""
    base = {
        "sku": "TEST-001",
        "name": "Test T-Shirt",
        "brand": "TestBrand",
        "category": "Men",
        "price": 999.0,
        "discount_percentage": 10.0,
        "stock_quantity": 100,
        "description": "A test product",
        "available_sizes": ["S", "M", "L"],
        "available_colors": ["Black", "White"],
        "image_urls": [],
    }
    base.update(overrides)
    return base


async def _create_product(client: AsyncClient, **overrides) -> dict:
    """POST a product and assert 201. Return the response JSON."""
    resp = await client.post("/products/", json=_product_payload(**overrides))
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest_asyncio.fixture(autouse=True)
async def clean_products(db: AsyncDatabase) -> None:
    """
    Wipe the products collection before every test function.

    Using autouse=True means this runs automatically for every test in this
    module without needing to call it explicitly.  This guarantees that:
    - Tests start from a clean state regardless of order.
    - A failed test's leftover data doesn't contaminate the next test.
    - We don't need to repeat await db["products"].delete_many({}) everywhere.
    """
    await db["products"].delete_many({})
    yield
    # Teardown: clean again after the test (belt-and-suspenders)
    await db["products"].delete_many({})


# ── POST /products ─────────────────────────────────────────────────────────────

class TestCreateProduct:

    async def test_create_returns_201(self, client: AsyncClient, db: AsyncDatabase) -> None:
        resp = await client.post("/products/", json=_product_payload())
        assert resp.status_code == 201
        await db["products"].delete_many({})

    async def test_create_response_has_id(self, client: AsyncClient, db: AsyncDatabase) -> None:
        data = await _create_product(client)
        assert "_id" in data
        assert len(data["_id"]) == 24  # ObjectId hex string
        await db["products"].delete_many({})

    async def test_create_computes_final_price(self, client: AsyncClient, db: AsyncDatabase) -> None:
        # price=1000, discount=10% → final_price=900
        data = await _create_product(client, price=1000.0, discount_percentage=10.0)
        assert data["final_price"] == 900.0
        await db["products"].delete_many({})

    async def test_create_sku_stored_uppercase(self, client: AsyncClient, db: AsyncDatabase) -> None:
        data = await _create_product(client, sku="shirt-001")
        assert data["sku"] == "SHIRT-001"
        await db["products"].delete_many({})

    async def test_create_stores_in_mongodb(self, client: AsyncClient, db: AsyncDatabase) -> None:
        data = await _create_product(client)
        doc = await db["products"].find_one({"sku": "TEST-001"})
        assert doc is not None
        assert doc["name"] == "Test T-Shirt"
        await db["products"].delete_many({})

    async def test_duplicate_sku_returns_409(self, client: AsyncClient, db: AsyncDatabase) -> None:
        await _create_product(client)
        resp = await client.post("/products/", json=_product_payload())
        assert resp.status_code == 409
        body = resp.json()
        assert body["error"] == "duplicate_sku"
        await db["products"].delete_many({})

    async def test_missing_required_field_returns_422(self, client: AsyncClient) -> None:
        payload = _product_payload()
        del payload["name"]
        resp = await client.post("/products/", json=payload)
        assert resp.status_code == 422

    async def test_negative_price_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post("/products/", json=_product_payload(price=-1.0))
        assert resp.status_code == 422

    async def test_discount_above_90_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/products/", json=_product_payload(discount_percentage=95.0)
        )
        assert resp.status_code == 422

    async def test_zero_discount_sets_final_price_equal_to_price(
        self, client: AsyncClient, db: AsyncDatabase
    ) -> None:
        data = await _create_product(client, price=500.0, discount_percentage=0.0)
        assert data["final_price"] == 500.0
        await db["products"].delete_many({})

    async def test_default_status_is_active(self, client: AsyncClient, db: AsyncDatabase) -> None:
        data = await _create_product(client)
        assert data["status"] == "active"
        await db["products"].delete_many({})

    async def test_response_contains_timestamps(self, client: AsyncClient, db: AsyncDatabase) -> None:
        data = await _create_product(client)
        assert "created_at" in data
        assert "updated_at" in data
        await db["products"].delete_many({})


# ── GET /products/{id} ────────────────────────────────────────────────────────

class TestGetProduct:

    async def test_get_by_id_returns_200(self, client: AsyncClient, db: AsyncDatabase) -> None:
        created = await _create_product(client)
        resp = await client.get(f"/products/{created['_id']}")
        assert resp.status_code == 200
        await db["products"].delete_many({})

    async def test_get_by_id_returns_correct_product(
        self, client: AsyncClient, db: AsyncDatabase
    ) -> None:
        created = await _create_product(client, name="Unique Blazer")
        resp = await client.get(f"/products/{created['_id']}")
        assert resp.json()["name"] == "Unique Blazer"
        await db["products"].delete_many({})

    async def test_get_nonexistent_id_returns_404(self, client: AsyncClient) -> None:
        fake_id = "000000000000000000000001"
        resp = await client.get(f"/products/{fake_id}")
        assert resp.status_code == 404
        assert resp.json()["error"] == "product_not_found"

    async def test_get_invalid_id_format_returns_404(self, client: AsyncClient) -> None:
        resp = await client.get("/products/not-a-valid-id")
        assert resp.status_code == 404

    async def test_get_response_has_final_price(self, client: AsyncClient, db: AsyncDatabase) -> None:
        created = await _create_product(client, price=2000.0, discount_percentage=25.0)
        resp = await client.get(f"/products/{created['_id']}")
        assert resp.json()["final_price"] == 1500.0
        await db["products"].delete_many({})


# ── GET /products (list) ──────────────────────────────────────────────────────

class TestListProducts:

    async def test_list_returns_200(self, client: AsyncClient) -> None:
        resp = await client.get("/products/")
        assert resp.status_code == 200

    async def test_list_response_has_pagination_fields(self, client: AsyncClient) -> None:
        resp = await client.get("/products/")
        body = resp.json()
        assert "items" in body
        assert "total" in body
        assert "page" in body
        assert "limit" in body
        assert "pages" in body

    async def test_list_empty_collection(self, client: AsyncClient, db: AsyncDatabase) -> None:
        await db["products"].delete_many({})
        resp = await client.get("/products/")
        body = resp.json()
        assert body["total"] == 0
        assert body["items"] == []

    async def test_list_pagination_limit(self, client: AsyncClient, db: AsyncDatabase) -> None:
        await db["products"].delete_many({})
        # Insert 5 products with unique SKUs
        for i in range(5):
            await _create_product(client, sku=f"PAGTEST-{i:03d}", name=f"Product {i}")
        resp = await client.get("/products/?limit=3&page=1")
        body = resp.json()
        assert len(body["items"]) == 3
        assert body["total"] == 5
        assert body["pages"] == 2
        await db["products"].delete_many({})

    async def test_list_page_2(self, client: AsyncClient, db: AsyncDatabase) -> None:
        await db["products"].delete_many({})
        for i in range(5):
            await _create_product(client, sku=f"PG2TEST-{i:03d}", name=f"Item {i}")
        resp = await client.get("/products/?limit=3&page=2")
        body = resp.json()
        assert len(body["items"]) == 2  # 5 total, 3 on page 1, 2 on page 2
        await db["products"].delete_many({})

    async def test_filter_by_category(self, client: AsyncClient, db: AsyncDatabase) -> None:
        await db["products"].delete_many({})
        await _create_product(client, sku="MEN-001", category="Men")
        await _create_product(client, sku="WOMEN-001", category="Women")
        resp = await client.get("/products/?category=Men")
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["category"] == "Men"
        await db["products"].delete_many({})

    async def test_filter_by_brand(self, client: AsyncClient, db: AsyncDatabase) -> None:
        await db["products"].delete_many({})
        await _create_product(client, sku="ARROW-001", brand="Arrow")
        await _create_product(client, sku="LEVI-001", brand="Levi's")
        resp = await client.get("/products/?brand=Arrow")
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["brand"] == "Arrow"
        await db["products"].delete_many({})

    async def test_filter_by_min_price(self, client: AsyncClient, db: AsyncDatabase) -> None:
        await db["products"].delete_many({})
        # price=500, discount=0 → final_price=500
        await _create_product(client, sku="CHEAP-001", price=500.0, discount_percentage=0.0)
        # price=2000, discount=0 → final_price=2000
        await _create_product(client, sku="PRICEY-001", price=2000.0, discount_percentage=0.0)
        resp = await client.get("/products/?min_price=1000")
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["sku"] == "PRICEY-001"
        await db["products"].delete_many({})

    async def test_filter_by_max_price(self, client: AsyncClient, db: AsyncDatabase) -> None:
        await db["products"].delete_many({})
        await _create_product(client, sku="CHEAP-002", price=500.0, discount_percentage=0.0)
        await _create_product(client, sku="PRICEY-002", price=2000.0, discount_percentage=0.0)
        resp = await client.get("/products/?max_price=999")
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["sku"] == "CHEAP-002"
        await db["products"].delete_many({})

    async def test_filter_by_status(self, client: AsyncClient, db: AsyncDatabase) -> None:
        await db["products"].delete_many({})
        await _create_product(client, sku="ACTIVE-001", status="active")
        await _create_product(client, sku="INACTIVE-001", status="inactive")
        resp = await client.get("/products/?status=inactive")
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["status"] == "inactive"
        await db["products"].delete_many({})

    async def test_list_items_omit_description(self, client: AsyncClient, db: AsyncDatabase) -> None:
        """List endpoint should omit description to keep payloads small."""
        await db["products"].delete_many({})
        await _create_product(client, sku="DESC-001")
        resp = await client.get("/products/")
        item = resp.json()["items"][0]
        assert "description" not in item
        await db["products"].delete_many({})

    async def test_invalid_page_returns_422(self, client: AsyncClient) -> None:
        resp = await client.get("/products/?page=0")
        assert resp.status_code == 422

    async def test_limit_above_100_returns_422(self, client: AsyncClient) -> None:
        resp = await client.get("/products/?limit=101")
        assert resp.status_code == 422


# ── PUT /products/{id} ────────────────────────────────────────────────────────

class TestUpdateProduct:

    async def test_update_name_returns_200(self, client: AsyncClient, db: AsyncDatabase) -> None:
        created = await _create_product(client)
        resp = await client.put(
            f"/products/{created['_id']}", json={"name": "Updated Shirt"}
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Shirt"
        await db["products"].delete_many({})

    async def test_update_price_recomputes_final_price(
        self, client: AsyncClient, db: AsyncDatabase
    ) -> None:
        created = await _create_product(client, price=1000.0, discount_percentage=10.0)
        # Update price only — discount stays 10%
        resp = await client.put(
            f"/products/{created['_id']}", json={"price": 2000.0}
        )
        assert resp.status_code == 200
        # new final_price = 2000 * 0.9 = 1800
        assert resp.json()["final_price"] == 1800.0
        await db["products"].delete_many({})

    async def test_update_discount_recomputes_final_price(
        self, client: AsyncClient, db: AsyncDatabase
    ) -> None:
        created = await _create_product(client, price=1000.0, discount_percentage=10.0)
        resp = await client.put(
            f"/products/{created['_id']}", json={"discount_percentage": 20.0}
        )
        # new final_price = 1000 * 0.8 = 800
        assert resp.json()["final_price"] == 800.0
        await db["products"].delete_many({})

    async def test_update_stock_quantity(self, client: AsyncClient, db: AsyncDatabase) -> None:
        created = await _create_product(client)
        resp = await client.put(
            f"/products/{created['_id']}", json={"stock_quantity": 200}
        )
        assert resp.json()["stock_quantity"] == 200
        await db["products"].delete_many({})

    async def test_update_nonexistent_product_returns_404(self, client: AsyncClient) -> None:
        resp = await client.put(
            "/products/000000000000000000000001", json={"name": "Ghost"}
        )
        assert resp.status_code == 404

    async def test_update_only_changes_sent_fields(
        self, client: AsyncClient, db: AsyncDatabase
    ) -> None:
        created = await _create_product(client, brand="OriginalBrand")
        resp = await client.put(
            f"/products/{created['_id']}", json={"name": "New Name"}
        )
        # brand should be unchanged
        assert resp.json()["brand"] == "OriginalBrand"
        assert resp.json()["name"] == "New Name"
        await db["products"].delete_many({})

    async def test_update_status_to_inactive(self, client: AsyncClient, db: AsyncDatabase) -> None:
        created = await _create_product(client)
        resp = await client.put(
            f"/products/{created['_id']}", json={"status": "inactive"}
        )
        assert resp.json()["status"] == "inactive"
        await db["products"].delete_many({})


# ── DELETE /products/{id} ─────────────────────────────────────────────────────

class TestDeleteProduct:

    async def test_delete_returns_204(self, client: AsyncClient, db: AsyncDatabase) -> None:
        created = await _create_product(client)
        resp = await client.delete(f"/products/{created['_id']}")
        assert resp.status_code == 204
        await db["products"].delete_many({})

    async def test_delete_removes_from_db(self, client: AsyncClient, db: AsyncDatabase) -> None:
        created = await _create_product(client)
        await client.delete(f"/products/{created['_id']}")
        doc = await db["products"].find_one({"sku": "TEST-001"})
        assert doc is None

    async def test_delete_nonexistent_returns_404(self, client: AsyncClient) -> None:
        resp = await client.delete("/products/000000000000000000000001")
        assert resp.status_code == 404
        assert resp.json()["error"] == "product_not_found"

    async def test_get_after_delete_returns_404(self, client: AsyncClient, db: AsyncDatabase) -> None:
        created = await _create_product(client)
        await client.delete(f"/products/{created['_id']}")
        resp = await client.get(f"/products/{created['_id']}")
        assert resp.status_code == 404
