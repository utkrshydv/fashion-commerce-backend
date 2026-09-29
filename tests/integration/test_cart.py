"""
tests/integration/test_cart.py

Integration tests for the shopping cart API.

User identity is simulated via the X-User-ID header.
Two user IDs are used throughout to verify cart isolation.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from pymongo.asynchronous.database import AsyncDatabase

USER_A = "user-001"
USER_B = "user-002"
HEADERS_A = {"X-User-ID": USER_A}
HEADERS_B = {"X-User-ID": USER_B}


# ── Helpers / fixtures ────────────────────────────────────────────────────────

def _product(sku: str = "CART-001", price: float = 1000.0, stock: int = 100,
             status: str = "active") -> dict:
    return {
        "sku": sku, "name": f"Product {sku}", "brand": "Brand",
        "category": "Men", "price": price, "discount_percentage": 0.0,
        "stock_quantity": stock, "description": "", "status": status,
        "available_sizes": ["M"], "available_colors": ["Black"],
        "image_urls": ["http://img.example.com/1.jpg"],
    }


@pytest_asyncio.fixture(autouse=True)
async def clean_all(db: AsyncDatabase) -> None:
    await db["products"].delete_many({})
    await db["carts"].delete_many({})
    yield
    await db["products"].delete_many({})
    await db["carts"].delete_many({})


async def _create_product(client: AsyncClient, **kw) -> dict:
    r = await client.post("/products/", json=_product(**kw))
    assert r.status_code == 201, r.text
    return r.json()


# ── GET /cart ─────────────────────────────────────────────────────────────────

class TestGetCart:

    async def test_get_cart_returns_200(self, client: AsyncClient) -> None:
        resp = await client.get("/cart/", headers=HEADERS_A)
        assert resp.status_code == 200

    async def test_get_cart_creates_empty_cart(self, client: AsyncClient) -> None:
        resp = await client.get("/cart/", headers=HEADERS_A)
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 0.0
        assert body["item_count"] == 0

    async def test_get_cart_missing_header_returns_422(self, client: AsyncClient) -> None:
        resp = await client.get("/cart/")
        assert resp.status_code == 422

    async def test_carts_are_isolated_per_user(self, client: AsyncClient) -> None:
        p = await _create_product(client)
        await client.post("/cart/items", headers=HEADERS_A,
                          json={"product_id": p["_id"], "quantity": 2})
        cart_b = await client.get("/cart/", headers=HEADERS_B)
        assert cart_b.json()["item_count"] == 0


# ── POST /cart/items ──────────────────────────────────────────────────────────

class TestAddItem:

    async def test_add_item_returns_200(self, client: AsyncClient) -> None:
        p = await _create_product(client)
        resp = await client.post("/cart/items", headers=HEADERS_A,
                                 json={"product_id": p["_id"], "quantity": 1})
        assert resp.status_code == 200

    async def test_add_item_appears_in_cart(self, client: AsyncClient) -> None:
        p = await _create_product(client)
        await client.post("/cart/items", headers=HEADERS_A,
                          json={"product_id": p["_id"], "quantity": 2})
        cart = await client.get("/cart/", headers=HEADERS_A)
        items = cart.json()["items"]
        assert len(items) == 1
        assert items[0]["quantity"] == 2

    async def test_add_item_computes_subtotal(self, client: AsyncClient) -> None:
        p = await _create_product(client, price=500.0)
        resp = await client.post("/cart/items", headers=HEADERS_A,
                                 json={"product_id": p["_id"], "quantity": 3})
        items = resp.json()["items"]
        assert items[0]["subtotal"] == 1500.0

    async def test_add_item_updates_total(self, client: AsyncClient) -> None:
        p = await _create_product(client, price=200.0)
        resp = await client.post("/cart/items", headers=HEADERS_A,
                                 json={"product_id": p["_id"], "quantity": 4})
        assert resp.json()["total"] == 800.0

    async def test_add_same_product_replaces_quantity(self, client: AsyncClient) -> None:
        """Adding the same product twice replaces quantity (not accumulate)."""
        p = await _create_product(client)
        await client.post("/cart/items", headers=HEADERS_A,
                          json={"product_id": p["_id"], "quantity": 1})
        resp = await client.post("/cart/items", headers=HEADERS_A,
                                 json={"product_id": p["_id"], "quantity": 5})
        cart = resp.json()
        assert cart["item_count"] == 5
        assert len(cart["items"]) == 1

    async def test_add_multiple_products(self, client: AsyncClient) -> None:
        p1 = await _create_product(client, sku="C-001", price=100.0)
        p2 = await _create_product(client, sku="C-002", price=200.0)
        await client.post("/cart/items", headers=HEADERS_A,
                          json={"product_id": p1["_id"], "quantity": 1})
        resp = await client.post("/cart/items", headers=HEADERS_A,
                                 json={"product_id": p2["_id"], "quantity": 2})
        assert resp.json()["total"] == 500.0  # 100 + 400
        assert len(resp.json()["items"]) == 2

    async def test_add_inactive_product_returns_422(self, client: AsyncClient) -> None:
        p = await _create_product(client, sku="INACTIVE-001", status="inactive")
        resp = await client.post("/cart/items", headers=HEADERS_A,
                                 json={"product_id": p["_id"], "quantity": 1})
        assert resp.status_code == 422
        assert resp.json()["error"] == "inactive_product"

    async def test_add_more_than_stock_returns_422(self, client: AsyncClient) -> None:
        p = await _create_product(client, stock=5)
        resp = await client.post("/cart/items", headers=HEADERS_A,
                                 json={"product_id": p["_id"], "quantity": 10})
        assert resp.status_code == 422
        assert resp.json()["error"] == "insufficient_stock"

    async def test_add_nonexistent_product_returns_404(self, client: AsyncClient) -> None:
        resp = await client.post("/cart/items", headers=HEADERS_A,
                                 json={"product_id": "000000000000000000000001", "quantity": 1})
        assert resp.status_code == 404

    async def test_add_item_snapshots_price(self, client: AsyncClient) -> None:
        """Price should be snapshotted at add-time, not reread on every GET."""
        p = await _create_product(client, price=100.0)
        await client.post("/cart/items", headers=HEADERS_A,
                          json={"product_id": p["_id"], "quantity": 1})
        # Update price in catalog
        await client.put(f"/products/{p['_id']}", json={"price": 999.0})
        # Cart should still show original price
        cart = await client.get("/cart/", headers=HEADERS_A)
        assert cart.json()["items"][0]["unit_price"] == 100.0


# ── PUT /cart/items/{product_id} ──────────────────────────────────────────────

class TestUpdateItem:

    async def test_update_quantity_returns_200(self, client: AsyncClient) -> None:
        p = await _create_product(client)
        await client.post("/cart/items", headers=HEADERS_A,
                          json={"product_id": p["_id"], "quantity": 1})
        resp = await client.put(f"/cart/items/{p['_id']}", headers=HEADERS_A,
                                json={"quantity": 5})
        assert resp.status_code == 200
        assert resp.json()["items"][0]["quantity"] == 5

    async def test_update_recomputes_subtotal(self, client: AsyncClient) -> None:
        p = await _create_product(client, price=100.0)
        await client.post("/cart/items", headers=HEADERS_A,
                          json={"product_id": p["_id"], "quantity": 1})
        resp = await client.put(f"/cart/items/{p['_id']}", headers=HEADERS_A,
                                json={"quantity": 3})
        assert resp.json()["items"][0]["subtotal"] == 300.0
        assert resp.json()["total"] == 300.0

    async def test_update_item_not_in_cart_returns_404(self, client: AsyncClient) -> None:
        p = await _create_product(client)
        resp = await client.put(f"/cart/items/{p['_id']}", headers=HEADERS_A,
                                json={"quantity": 2})
        assert resp.status_code == 404


# ── DELETE /cart/items/{product_id} ──────────────────────────────────────────

class TestRemoveItem:

    async def test_remove_item_returns_200(self, client: AsyncClient) -> None:
        p = await _create_product(client)
        await client.post("/cart/items", headers=HEADERS_A,
                          json={"product_id": p["_id"], "quantity": 1})
        resp = await client.delete(f"/cart/items/{p['_id']}", headers=HEADERS_A)
        assert resp.status_code == 200

    async def test_remove_item_empties_cart(self, client: AsyncClient) -> None:
        p = await _create_product(client)
        await client.post("/cart/items", headers=HEADERS_A,
                          json={"product_id": p["_id"], "quantity": 1})
        resp = await client.delete(f"/cart/items/{p['_id']}", headers=HEADERS_A)
        assert resp.json()["items"] == []
        assert resp.json()["total"] == 0.0

    async def test_remove_nonexistent_item_returns_404(self, client: AsyncClient) -> None:
        p = await _create_product(client)
        resp = await client.delete(f"/cart/items/{p['_id']}", headers=HEADERS_A)
        assert resp.status_code == 404


# ── DELETE /cart ──────────────────────────────────────────────────────────────

class TestClearCart:

    async def test_clear_cart_returns_empty_cart(self, client: AsyncClient) -> None:
        p = await _create_product(client)
        await client.post("/cart/items", headers=HEADERS_A,
                          json={"product_id": p["_id"], "quantity": 3})
        resp = await client.delete("/cart/", headers=HEADERS_A)
        assert resp.status_code == 200
        assert resp.json()["items"] == []
        assert resp.json()["total"] == 0.0
        assert resp.json()["item_count"] == 0
