"""
tests/integration/test_inventory.py

Integration tests for the inventory API.

Tests cover:
- GET /inventory/{product_id}: get/create record
- POST /inventory/{product_id}/adjust: add and deduct stock
- GET /inventory/low-stock: low stock report
- Edge cases: product not found, insufficient stock
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from pymongo.asynchronous.database import AsyncDatabase


# ── Helpers / fixtures ────────────────────────────────────────────────────────

def _product(sku: str = "INV-001", stock: int = 100) -> dict:
    return {
        "sku": sku, "name": "Test Product", "brand": "Brand",
        "category": "Men", "price": 999.0, "discount_percentage": 0.0,
        "stock_quantity": stock, "description": "", "available_sizes": ["M"],
        "available_colors": ["Black"], "image_urls": ["http://img.example.com/1.jpg"],
    }


@pytest_asyncio.fixture(autouse=True)
async def clean_collections(db: AsyncDatabase) -> None:
    await db["products"].delete_many({})
    await db["inventory"].delete_many({})
    yield
    await db["products"].delete_many({})
    await db["inventory"].delete_many({})


async def _create_product(client: AsyncClient, sku: str = "INV-001") -> dict:
    r = await client.post("/products/", json=_product(sku))
    assert r.status_code == 201, r.text
    return r.json()


# ── GET /inventory/{product_id} ───────────────────────────────────────────────

class TestGetInventory:

    async def test_get_returns_200(self, client: AsyncClient) -> None:
        p = await _create_product(client)
        resp = await client.get(f"/inventory/{p['_id']}")
        assert resp.status_code == 200

    async def test_get_creates_record_with_zero_quantity(self, client: AsyncClient) -> None:
        p = await _create_product(client)
        resp = await client.get(f"/inventory/{p['_id']}")
        body = resp.json()
        assert body["quantity"] == 0
        assert body["product_id"] == p["_id"]

    async def test_get_nonexistent_product_returns_404(self, client: AsyncClient) -> None:
        resp = await client.get("/inventory/000000000000000000000001")
        assert resp.status_code == 404

    async def test_get_response_has_is_low_stock_field(self, client: AsyncClient) -> None:
        p = await _create_product(client)
        resp = await client.get(f"/inventory/{p['_id']}")
        assert "is_low_stock" in resp.json()

    async def test_zero_quantity_is_low_stock(self, client: AsyncClient) -> None:
        p = await _create_product(client)
        resp = await client.get(f"/inventory/{p['_id']}")
        assert resp.json()["is_low_stock"] is True  # 0 <= default threshold 10


# ── POST /inventory/{product_id}/adjust ──────────────────────────────────────

class TestAdjustStock:

    async def test_add_stock_returns_200(self, client: AsyncClient) -> None:
        p = await _create_product(client)
        resp = await client.post(
            f"/inventory/{p['_id']}/adjust", json={"delta": 50}
        )
        assert resp.status_code == 200

    async def test_add_stock_increases_quantity(self, client: AsyncClient) -> None:
        p = await _create_product(client)
        await client.post(f"/inventory/{p['_id']}/adjust", json={"delta": 50})
        resp = await client.get(f"/inventory/{p['_id']}")
        assert resp.json()["quantity"] == 50

    async def test_multiple_additions_accumulate(self, client: AsyncClient) -> None:
        p = await _create_product(client)
        await client.post(f"/inventory/{p['_id']}/adjust", json={"delta": 30})
        await client.post(f"/inventory/{p['_id']}/adjust", json={"delta": 20})
        resp = await client.get(f"/inventory/{p['_id']}")
        assert resp.json()["quantity"] == 50

    async def test_deduct_stock_decreases_quantity(self, client: AsyncClient) -> None:
        p = await _create_product(client)
        await client.post(f"/inventory/{p['_id']}/adjust", json={"delta": 100})
        await client.post(f"/inventory/{p['_id']}/adjust", json={"delta": -30})
        resp = await client.get(f"/inventory/{p['_id']}")
        assert resp.json()["quantity"] == 70

    async def test_deduct_exact_available_stock_succeeds(self, client: AsyncClient) -> None:
        p = await _create_product(client)
        await client.post(f"/inventory/{p['_id']}/adjust", json={"delta": 50})
        resp = await client.post(f"/inventory/{p['_id']}/adjust", json={"delta": -50})
        assert resp.status_code == 200
        assert resp.json()["quantity"] == 0

    async def test_deduct_more_than_available_returns_422(self, client: AsyncClient) -> None:
        p = await _create_product(client)
        await client.post(f"/inventory/{p['_id']}/adjust", json={"delta": 10})
        resp = await client.post(f"/inventory/{p['_id']}/adjust", json={"delta": -50})
        assert resp.status_code == 422
        assert resp.json()["error"] == "insufficient_stock"

    async def test_deduct_from_zero_stock_returns_422(self, client: AsyncClient) -> None:
        p = await _create_product(client)
        resp = await client.post(f"/inventory/{p['_id']}/adjust", json={"delta": -1})
        assert resp.status_code == 422

    async def test_adjust_nonexistent_product_returns_404(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/inventory/000000000000000000000001/adjust", json={"delta": 10}
        )
        assert resp.status_code == 404

    async def test_is_low_stock_updates_after_restock(self, client: AsyncClient) -> None:
        p = await _create_product(client)
        await client.post(f"/inventory/{p['_id']}/adjust", json={"delta": 100})
        resp = await client.get(f"/inventory/{p['_id']}")
        assert resp.json()["is_low_stock"] is False  # 100 > threshold 10


# ── GET /inventory/low-stock ─────────────────────────────────────────────────

class TestLowStockReport:

    async def test_low_stock_returns_200(self, client: AsyncClient) -> None:
        resp = await client.get("/inventory/low-stock")
        assert resp.status_code == 200

    async def test_low_stock_returns_list(self, client: AsyncClient) -> None:
        resp = await client.get("/inventory/low-stock")
        assert isinstance(resp.json(), list)

    async def test_zero_stock_appears_in_report(self, client: AsyncClient) -> None:
        p = await _create_product(client)
        await client.get(f"/inventory/{p['_id']}")  # creates record with qty=0
        resp = await client.get("/inventory/low-stock")
        ids = [item["product_id"] for item in resp.json()]
        assert p["_id"] in ids

    async def test_high_stock_not_in_default_report(self, client: AsyncClient) -> None:
        p = await _create_product(client)
        await client.post(f"/inventory/{p['_id']}/adjust", json={"delta": 100})
        resp = await client.get("/inventory/low-stock")
        ids = [item["product_id"] for item in resp.json()]
        assert p["_id"] not in ids

    async def test_custom_threshold(self, client: AsyncClient) -> None:
        p = await _create_product(client)
        await client.post(f"/inventory/{p['_id']}/adjust", json={"delta": 50})
        # With threshold=100, qty=50 should appear
        resp = await client.get("/inventory/low-stock?threshold=100")
        ids = [item["product_id"] for item in resp.json()]
        assert p["_id"] in ids
