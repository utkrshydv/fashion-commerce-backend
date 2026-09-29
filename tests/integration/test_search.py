"""
tests/integration/test_search.py

Integration tests for GET /search.

These tests exercise the full MongoDB text search pipeline:
  HTTP request → FastAPI → ProductService.search_products →
  ProductRepository.text_search → MongoDB $text index → response

Test isolation: the autouse fixture wipes the products collection before
and after each test so text search results are deterministic.

Note on text search and index: MongoDB text indexes are background-indexed.
After inserting a document, the text index is updated synchronously in the
same operation (for small collections). All tests will work correctly.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from pymongo.asynchronous.database import AsyncDatabase


# ── Helpers / fixtures ────────────────────────────────────────────────────────

def _product(sku: str, name: str, brand: str = "Brand", category: str = "Men",
             price: float = 999.0, description: str = "") -> dict:
    return {
        "sku": sku, "name": name, "brand": brand, "category": category,
        "price": price, "discount_percentage": 0.0, "stock_quantity": 10,
        "description": description, "available_sizes": ["M"],
        "available_colors": ["Black"], "image_urls": [],
    }


@pytest_asyncio.fixture(autouse=True)
async def clean_products(db: AsyncDatabase) -> None:
    await db["products"].delete_many({})
    yield
    await db["products"].delete_many({})


async def _seed(client: AsyncClient, *payloads: dict) -> list:
    results = []
    for p in payloads:
        r = await client.post("/products/", json=p)
        assert r.status_code == 201, r.text
        results.append(r.json())
    return results


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestSearchEndpoint:

    async def test_search_returns_200(self, client: AsyncClient) -> None:
        resp = await client.get("/search/?q=shirt")
        assert resp.status_code == 200

    async def test_search_response_has_expected_fields(self, client: AsyncClient) -> None:
        resp = await client.get("/search/?q=shirt")
        body = resp.json()
        assert "items" in body
        assert "total" in body
        assert "page" in body
        assert "limit" in body
        assert "pages" in body
        assert "query" in body

    async def test_search_echoes_query(self, client: AsyncClient) -> None:
        resp = await client.get("/search/?q=jeans")
        assert resp.json()["query"] == "jeans"

    async def test_query_too_short_returns_422(self, client: AsyncClient) -> None:
        resp = await client.get("/search/?q=a")
        assert resp.status_code == 422

    async def test_missing_query_returns_422(self, client: AsyncClient) -> None:
        resp = await client.get("/search/")
        assert resp.status_code == 422

    async def test_search_finds_by_name(self, client: AsyncClient) -> None:
        await _seed(
            client,
            _product("SHIRT-001", "Classic White Shirt"),
            _product("JEANS-001", "Slim Fit Denim Jeans"),
        )
        resp = await client.get("/search/?q=shirt")
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["name"] == "Classic White Shirt"

    async def test_search_finds_by_brand(self, client: AsyncClient) -> None:
        await _seed(
            client,
            _product("ARROW-001", "Formal Shirt", brand="Arrow"),
            _product("LEVI-001", "Casual Jeans", brand="Levis"),
        )
        resp = await client.get("/search/?q=Arrow")
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["brand"] == "Arrow"

    async def test_search_finds_by_description(self, client: AsyncClient) -> None:
        await _seed(
            client,
            _product("DESC-001", "Blue Top", description="handcrafted organic cotton tee"),
            _product("DESC-002", "Red Top", description="standard polyester blend"),
        )
        resp = await client.get("/search/?q=organic")
        body = resp.json()
        assert body["total"] == 1

    async def test_search_no_results_returns_empty(self, client: AsyncClient) -> None:
        await _seed(client, _product("P001", "Blue Shirt"))
        resp = await client.get("/search/?q=nonexistentxyzabc")
        body = resp.json()
        assert body["total"] == 0
        assert body["items"] == []

    async def test_search_results_have_score(self, client: AsyncClient) -> None:
        await _seed(client, _product("S001", "Striped Shirt"))
        resp = await client.get("/search/?q=shirt")
        item = resp.json()["items"][0]
        assert "score" in item
        assert item["score"] is not None
        assert item["score"] > 0

    async def test_search_with_category_filter(self, client: AsyncClient) -> None:
        await _seed(
            client,
            _product("M001", "Classic Shirt", category="Men"),
            _product("W001", "Classic Blouse", category="Women"),
        )
        resp = await client.get("/search/?q=classic&category=Men")
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["category"] == "Men"

    async def test_search_pagination_limit(self, client: AsyncClient) -> None:
        await _seed(
            client,
            *[_product(f"SRCH-{i:03d}", f"Cotton Shirt {i}") for i in range(5)]
        )
        resp = await client.get("/search/?q=cotton&limit=3&page=1")
        body = resp.json()
        assert len(body["items"]) == 3
        assert body["total"] == 5
        assert body["pages"] == 2

    async def test_search_items_omit_description(self, client: AsyncClient) -> None:
        await _seed(client, _product("D001", "Nice Shirt", description="A very long desc"))
        resp = await client.get("/search/?q=nice")
        item = resp.json()["items"][0]
        assert "description" not in item
