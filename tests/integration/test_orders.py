"""
tests/integration/test_orders.py

Integration tests for the orders API.

Tests cover the full checkout flow:
  create product → stock inventory → fill cart → place order
  and then: list, get, status transitions, ownership enforcement.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from pymongo.asynchronous.database import AsyncDatabase

USER_A = "order-user-001"
USER_B = "order-user-002"
HA = {"X-User-ID": USER_A}
HB = {"X-User-ID": USER_B}
ADDR = "123 Test Street, Mumbai 400001"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def clean_all(db: AsyncDatabase) -> None:
    await db["products"].delete_many({})
    await db["inventory"].delete_many({})
    await db["carts"].delete_many({})
    await db["orders"].delete_many({})
    yield
    await db["products"].delete_many({})
    await db["inventory"].delete_many({})
    await db["carts"].delete_many({})
    await db["orders"].delete_many({})


def _product(sku: str = "ORD-001", price: float = 500.0) -> dict:
    return {
        "sku": sku, "name": f"Product {sku}", "brand": "Brand",
        "category": "Men", "price": price, "discount_percentage": 0.0,
        "stock_quantity": 100, "description": "", "status": "active",
        "available_sizes": ["M"], "available_colors": ["Black"],
        "image_urls": ["http://img.example.com/1.jpg"],
    }


async def _create_product(client: AsyncClient, **kw) -> dict:
    r = await client.post("/products/", json=_product(**kw))
    assert r.status_code == 201, r.text
    return r.json()


async def _stock_product(client: AsyncClient, product_id: str, qty: int = 50) -> None:
    r = await client.post(f"/inventory/{product_id}/adjust", json={"delta": qty})
    assert r.status_code == 200, r.text


async def _add_to_cart(client: AsyncClient, product_id: str, qty: int = 1,
                       headers: dict = HA) -> None:
    r = await client.post("/cart/items", headers=headers,
                          json={"product_id": product_id, "quantity": qty})
    assert r.status_code == 200, r.text


async def _place_order(client: AsyncClient, headers: dict = HA,
                       address: str = ADDR) -> dict:
    r = await client.post("/orders/", headers=headers,
                          json={"shipping_address": address})
    assert r.status_code == 201, r.text
    return r.json()


# ── POST /orders ──────────────────────────────────────────────────────────────

class TestPlaceOrder:

    async def test_place_order_returns_201(self, client: AsyncClient) -> None:
        p = await _create_product(client)
        await _stock_product(client, p["_id"])
        await _add_to_cart(client, p["_id"])
        resp = await client.post("/orders/", headers=HA,
                                 json={"shipping_address": ADDR})
        assert resp.status_code == 201

    async def test_order_has_correct_items(self, client: AsyncClient) -> None:
        p = await _create_product(client, sku="ORD-A1", price=300.0)
        await _stock_product(client, p["_id"])
        await _add_to_cart(client, p["_id"], qty=2)
        order = await _place_order(client)
        assert len(order["items"]) == 1
        assert order["items"][0]["quantity"] == 2
        assert order["items"][0]["subtotal"] == 600.0

    async def test_order_total_matches_cart(self, client: AsyncClient) -> None:
        p1 = await _create_product(client, sku="ORD-B1", price=100.0)
        p2 = await _create_product(client, sku="ORD-B2", price=200.0)
        await _stock_product(client, p1["_id"])
        await _stock_product(client, p2["_id"])
        await _add_to_cart(client, p1["_id"], qty=2)
        await _add_to_cart(client, p2["_id"], qty=1)
        order = await _place_order(client)
        assert order["total"] == 400.0  # 200 + 200

    async def test_order_status_is_pending(self, client: AsyncClient) -> None:
        p = await _create_product(client)
        await _stock_product(client, p["_id"])
        await _add_to_cart(client, p["_id"])
        order = await _place_order(client)
        assert order["status"] == "pending"

    async def test_order_deducts_inventory(self, client: AsyncClient, db: AsyncDatabase) -> None:
        p = await _create_product(client)
        await _stock_product(client, p["_id"], qty=50)
        await _add_to_cart(client, p["_id"], qty=3)
        await _place_order(client)
        inv = await db["inventory"].find_one({"product_id": p["_id"]})
        assert inv["quantity"] == 47

    async def test_order_clears_cart(self, client: AsyncClient) -> None:
        p = await _create_product(client)
        await _stock_product(client, p["_id"])
        await _add_to_cart(client, p["_id"])
        await _place_order(client)
        cart = await client.get("/cart/", headers=HA)
        assert cart.json()["item_count"] == 0

    async def test_order_saves_shipping_address(self, client: AsyncClient) -> None:
        p = await _create_product(client)
        await _stock_product(client, p["_id"])
        await _add_to_cart(client, p["_id"])
        order = await _place_order(client, address="456 Custom Road, Delhi 110001")
        assert order["shipping_address"] == "456 Custom Road, Delhi 110001"

    async def test_empty_cart_returns_400(self, client: AsyncClient) -> None:
        resp = await client.post("/orders/", headers=HA,
                                 json={"shipping_address": ADDR})
        assert resp.status_code == 400
        assert resp.json()["error"] == "validation_error"

    async def test_insufficient_stock_returns_422(self, client: AsyncClient) -> None:
        p = await _create_product(client)
        # Stock only 2, cart wants 10
        await _stock_product(client, p["_id"], qty=2)
        await _add_to_cart(client, p["_id"], qty=10)

        # Manually override the cart item to bypass the add_to_cart stock check
        # (we test the order-time check here, not the cart check)
        # So let's add with qty=2 (within stock), then stock drops to 0, then try order
        await _add_to_cart(client, p["_id"], qty=2)
        # Drain inventory
        await client.post(f"/inventory/{p['_id']}/adjust", json={"delta": -2})
        # Now place order with 2 in cart but 0 stock
        resp = await client.post("/orders/", headers=HA,
                                 json={"shipping_address": ADDR})
        assert resp.status_code == 422
        assert resp.json()["error"] == "insufficient_stock"

    async def test_missing_header_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post("/orders/", json={"shipping_address": ADDR})
        assert resp.status_code == 422

    async def test_short_address_returns_422(self, client: AsyncClient) -> None:
        p = await _create_product(client)
        await _stock_product(client, p["_id"])
        await _add_to_cart(client, p["_id"])
        resp = await client.post("/orders/", headers=HA,
                                 json={"shipping_address": "ab"})
        assert resp.status_code == 422


# ── GET /orders/{id} ─────────────────────────────────────────────────────────

class TestGetOrder:

    async def test_get_order_returns_200(self, client: AsyncClient) -> None:
        p = await _create_product(client)
        await _stock_product(client, p["_id"])
        await _add_to_cart(client, p["_id"])
        order = await _place_order(client)
        resp = await client.get(f"/orders/{order['_id']}", headers=HA)
        assert resp.status_code == 200

    async def test_get_order_returns_correct_data(self, client: AsyncClient) -> None:
        p = await _create_product(client, sku="GET-001", price=250.0)
        await _stock_product(client, p["_id"])
        await _add_to_cart(client, p["_id"], qty=4)
        placed = await _place_order(client)
        fetched = (await client.get(f"/orders/{placed['_id']}", headers=HA)).json()
        assert fetched["total"] == 1000.0
        assert fetched["item_count"] == 4

    async def test_get_nonexistent_order_returns_404(self, client: AsyncClient) -> None:
        resp = await client.get("/orders/000000000000000000000001", headers=HA)
        assert resp.status_code == 404

    async def test_get_other_users_order_returns_404(self, client: AsyncClient) -> None:
        """User B cannot see User A's order."""
        p = await _create_product(client)
        await _stock_product(client, p["_id"])
        await _add_to_cart(client, p["_id"])
        order = await _place_order(client, headers=HA)
        resp = await client.get(f"/orders/{order['_id']}", headers=HB)
        assert resp.status_code == 404


# ── GET /orders ───────────────────────────────────────────────────────────────

class TestListOrders:

    async def test_list_orders_returns_200(self, client: AsyncClient) -> None:
        resp = await client.get("/orders/", headers=HA)
        assert resp.status_code == 200

    async def test_list_empty_returns_zero(self, client: AsyncClient) -> None:
        resp = await client.get("/orders/", headers=HA)
        assert resp.json()["total"] == 0

    async def test_list_returns_placed_orders(self, client: AsyncClient) -> None:
        p = await _create_product(client)
        await _stock_product(client, p["_id"])
        await _add_to_cart(client, p["_id"])
        await _place_order(client)
        resp = await client.get("/orders/", headers=HA)
        assert resp.json()["total"] == 1

    async def test_list_isolates_by_user(self, client: AsyncClient) -> None:
        p = await _create_product(client)
        await _stock_product(client, p["_id"], qty=100)
        await _add_to_cart(client, p["_id"], qty=1, headers=HA)
        await _add_to_cart(client, p["_id"], qty=1, headers=HB)
        await _place_order(client, headers=HA)
        await _place_order(client, headers=HB)
        a_orders = await client.get("/orders/", headers=HA)
        b_orders = await client.get("/orders/", headers=HB)
        assert a_orders.json()["total"] == 1
        assert b_orders.json()["total"] == 1

    async def test_list_filter_by_status(self, client: AsyncClient) -> None:
        p = await _create_product(client)
        await _stock_product(client, p["_id"], qty=100)
        await _add_to_cart(client, p["_id"])
        order = await _place_order(client)
        # Confirm the order
        await client.put(f"/orders/{order['_id']}/status", headers=HA,
                         json={"status": "confirmed"})
        pending = await client.get("/orders/?status=pending", headers=HA)
        confirmed = await client.get("/orders/?status=confirmed", headers=HA)
        assert pending.json()["total"] == 0
        assert confirmed.json()["total"] == 1


# ── PUT /orders/{id}/status ───────────────────────────────────────────────────

class TestUpdateOrderStatus:

    async def _setup_order(self, client: AsyncClient) -> dict:
        p = await _create_product(client)
        await _stock_product(client, p["_id"])
        await _add_to_cart(client, p["_id"])
        return await _place_order(client)

    async def test_pending_to_confirmed(self, client: AsyncClient) -> None:
        order = await self._setup_order(client)
        resp = await client.put(f"/orders/{order['_id']}/status", headers=HA,
                                json={"status": "confirmed"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "confirmed"

    async def test_confirmed_to_shipped(self, client: AsyncClient) -> None:
        order = await self._setup_order(client)
        await client.put(f"/orders/{order['_id']}/status", headers=HA,
                         json={"status": "confirmed"})
        resp = await client.put(f"/orders/{order['_id']}/status", headers=HA,
                                json={"status": "shipped"})
        assert resp.json()["status"] == "shipped"

    async def test_shipped_to_delivered(self, client: AsyncClient) -> None:
        order = await self._setup_order(client)
        await client.put(f"/orders/{order['_id']}/status", headers=HA,
                         json={"status": "confirmed"})
        await client.put(f"/orders/{order['_id']}/status", headers=HA,
                         json={"status": "shipped"})
        resp = await client.put(f"/orders/{order['_id']}/status", headers=HA,
                                json={"status": "delivered"})
        assert resp.json()["status"] == "delivered"

    async def test_pending_to_cancelled(self, client: AsyncClient) -> None:
        order = await self._setup_order(client)
        resp = await client.put(f"/orders/{order['_id']}/status", headers=HA,
                                json={"status": "cancelled"})
        assert resp.json()["status"] == "cancelled"

    async def test_invalid_transition_returns_400(self, client: AsyncClient) -> None:
        order = await self._setup_order(client)
        resp = await client.put(f"/orders/{order['_id']}/status", headers=HA,
                                json={"status": "delivered"})  # pending → delivered not allowed
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_status_transition"

    async def test_shipped_cannot_be_cancelled(self, client: AsyncClient) -> None:
        order = await self._setup_order(client)
        await client.put(f"/orders/{order['_id']}/status", headers=HA,
                         json={"status": "confirmed"})
        await client.put(f"/orders/{order['_id']}/status", headers=HA,
                         json={"status": "shipped"})
        resp = await client.put(f"/orders/{order['_id']}/status", headers=HA,
                                json={"status": "cancelled"})
        assert resp.status_code == 400

    async def test_delivered_has_no_further_transitions(self, client: AsyncClient) -> None:
        order = await self._setup_order(client)
        for s in ["confirmed", "shipped", "delivered"]:
            await client.put(f"/orders/{order['_id']}/status", headers=HA,
                             json={"status": s})
        resp = await client.put(f"/orders/{order['_id']}/status", headers=HA,
                                json={"status": "cancelled"})
        assert resp.status_code == 400

    async def test_status_notes_stored(self, client: AsyncClient) -> None:
        order = await self._setup_order(client)
        resp = await client.put(f"/orders/{order['_id']}/status", headers=HA,
                                json={"status": "confirmed", "notes": "Payment verified"})
        assert resp.json()["status_notes"] == "Payment verified"

    async def test_update_other_users_order_returns_404(self, client: AsyncClient) -> None:
        order = await self._setup_order(client)
        resp = await client.put(f"/orders/{order['_id']}/status", headers=HB,
                                json={"status": "confirmed"})
        assert resp.status_code == 404
