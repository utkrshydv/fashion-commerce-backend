# Testing Guide

This document covers every way you can test the Fashion Commerce Backend,
from automated tests to manual API calls.

---

## 1. Automated Tests (296 tests)

### Prerequisites

- Python 3.12+, virtual environment activated
- MongoDB running locally on port 27017

### Run everything

```bash
pytest
```

Expected output: `296 passed in ~10s`

### Run with coverage report

```bash
pytest --cov=app --cov-report=term-missing
```

Expected: `Total coverage: 89.51% -- Required test coverage of 70.0% reached.`

### Run a specific category

```bash
# Unit tests only (no MongoDB needed — fast)
pytest tests/unit/ -v

# Integration tests only (requires MongoDB)
pytest tests/integration/ -v

# Specific feature
pytest tests/integration/test_products.py -v
pytest tests/integration/test_cart.py -v
pytest tests/integration/test_orders.py -v
pytest tests/integration/test_inventory.py -v
pytest tests/integration/test_search.py -v
pytest tests/integration/test_edge_cases.py -v

# Background jobs
pytest tests/unit/test_jobs.py -v
```

### Test isolation

Integration tests use a separate `fashion_commerce_test` database.
Each test class has an `autouse` fixture that wipes its collections before and after,
so tests never affect each other or your development data.

---

## 2. Manual Testing via Swagger UI

### Step 1: Start the API

```bash
uvicorn app.main:app --reload
```

Open http://localhost:8000/docs in your browser.

### Step 2: Seed the database

```bash
python scripts/seed_database.py
```

This creates 26 products, inventory, and 6 orders across 3 sample users.

### Step 3: Try each endpoint in Swagger

The Swagger UI at `/docs` lets you execute requests directly from the browser.
Every endpoint, parameter, and response schema is documented.

For endpoints that require `X-User-ID`, click "Authorize" (or use the padlock icon
on each endpoint) — but since there's no JWT auth yet, just pass the header
manually using the request field.

---

## 3. Manual Testing via curl

Start the API first: `uvicorn app.main:app --reload`

### Health check

```bash
curl http://localhost:8000/health
```

Expected:
```json
{"status":"ok","version":"0.1.0","environment":"development","database":"ok"}
```

---

### Products

**Create a product:**
```bash
curl -X POST http://localhost:8000/products/ \
  -H "Content-Type: application/json" \
  -d '{
    "sku": "TEST-001",
    "name": "Test Shirt",
    "brand": "TestBrand",
    "category": "Men",
    "price": 999.0,
    "discount_percentage": 10.0,
    "stock_quantity": 50,
    "description": "A test product",
    "status": "active",
    "available_sizes": ["S","M","L"],
    "available_colors": ["White","Black"],
    "image_urls": ["https://example.com/img.jpg"]
  }'
```

Expected: `201 Created` with the full product document including `_id` and `final_price: 899.1`.

**List products:**
```bash
# All active products (paginated)
curl "http://localhost:8000/products/?page=1&limit=10"

# Filter by category
curl "http://localhost:8000/products/?category=Women"

# Filter by price range
curl "http://localhost:8000/products/?min_price=500&max_price=2000"

# Sort by price ascending
curl "http://localhost:8000/products/?sort_by=price&sort_order=asc"

# Combine filters
curl "http://localhost:8000/products/?category=Men&min_price=1000&sort_by=price"
```

**Get a product by ID:**
```bash
# Replace <product_id> with a real _id from the list response
curl http://localhost:8000/products/<product_id>
```

**Update a product:**
```bash
curl -X PUT http://localhost:8000/products/<product_id> \
  -H "Content-Type: application/json" \
  -d '{"price": 1199.0, "discount_percentage": 15.0}'
```

**Delete a product:**
```bash
curl -X DELETE http://localhost:8000/products/<product_id>
```

---

### Search

```bash
# Search by name/brand/description
curl "http://localhost:8000/search/?q=shirt"

# Search with category filter
curl "http://localhost:8000/search/?q=jeans&category=Women"

# Search with price range
curl "http://localhost:8000/search/?q=jacket&max_price=3000"

# Paginate search results
curl "http://localhost:8000/search/?q=shirt&page=2&limit=5"
```

Results are sorted by relevance score (name matches rank higher than description matches).

---

### Inventory

```bash
# Get stock level (creates a record with qty=0 if none exists)
curl http://localhost:8000/inventory/<product_id>

# Add stock (positive delta)
curl -X POST http://localhost:8000/inventory/<product_id>/adjust \
  -H "Content-Type: application/json" \
  -d '{"delta": 50}'

# Deduct stock (negative delta)
curl -X POST http://localhost:8000/inventory/<product_id>/adjust \
  -H "Content-Type: application/json" \
  -d '{"delta": -10}'

# Try to deduct more than available (should return 422)
curl -X POST http://localhost:8000/inventory/<product_id>/adjust \
  -H "Content-Type: application/json" \
  -d '{"delta": -9999}'

# Get all low-stock products (default threshold: 10)
curl "http://localhost:8000/inventory/low-stock"

# Custom threshold
curl "http://localhost:8000/inventory/low-stock?threshold=50"
```

---

### Shopping Cart

The cart requires an `X-User-ID` header to identify the user.
Use any string as the user ID (e.g. `user-123`).

```bash
# Get cart (creates empty cart if none exists)
curl http://localhost:8000/cart/ \
  -H "X-User-ID: user-123"

# Add item to cart
curl -X POST http://localhost:8000/cart/items \
  -H "Content-Type: application/json" \
  -H "X-User-ID: user-123" \
  -d '{"product_id": "<product_id>", "quantity": 2}'

# Try adding an inactive product (should return 422)
# Try requesting more quantity than stock (should return 422)
curl -X POST http://localhost:8000/cart/items \
  -H "Content-Type: application/json" \
  -H "X-User-ID: user-123" \
  -d '{"product_id": "<product_id>", "quantity": 99999}'

# Update quantity
curl -X PUT http://localhost:8000/cart/items/<product_id> \
  -H "Content-Type: application/json" \
  -H "X-User-ID: user-123" \
  -d '{"quantity": 5}'

# Remove one item
curl -X DELETE http://localhost:8000/cart/items/<product_id> \
  -H "X-User-ID: user-123"

# Clear entire cart
curl -X DELETE http://localhost:8000/cart/ \
  -H "X-User-ID: user-123"
```

**Verify user isolation**: Add an item with `X-User-ID: user-123`, then GET the cart
with `X-User-ID: user-456`. The second cart should be empty.

---

### Orders (Full Checkout Flow)

**Step 1: Add items to cart**
```bash
curl -X POST http://localhost:8000/cart/items \
  -H "Content-Type: application/json" \
  -H "X-User-ID: user-123" \
  -d '{"product_id": "<product_id>", "quantity": 1}'
```

**Step 2: Place the order**
```bash
curl -X POST http://localhost:8000/orders/ \
  -H "Content-Type: application/json" \
  -H "X-User-ID: user-123" \
  -d '{"shipping_address": "123 Main Street, Mumbai 400001"}'
```

Expected: `201 Created`. Status is `pending`. Cart is now empty.

**Step 3: Verify cart was cleared**
```bash
curl http://localhost:8000/cart/ -H "X-User-ID: user-123"
# item_count should be 0
```

**Step 4: Verify inventory was deducted**
```bash
curl http://localhost:8000/inventory/<product_id>
# quantity should have decreased by the amount ordered
```

**Step 5: Advance the order status**
```bash
# Save the order _id from Step 2

# pending -> confirmed
curl -X PUT http://localhost:8000/orders/<order_id>/status \
  -H "Content-Type: application/json" \
  -H "X-User-ID: user-123" \
  -d '{"status": "confirmed"}'

# confirmed -> shipped
curl -X PUT http://localhost:8000/orders/<order_id>/status \
  -H "Content-Type: application/json" \
  -H "X-User-ID: user-123" \
  -d '{"status": "shipped"}'

# shipped -> delivered
curl -X PUT http://localhost:8000/orders/<order_id>/status \
  -H "Content-Type: application/json" \
  -H "X-User-ID: user-123" \
  -d '{"status": "delivered"}'

# Try an invalid transition (delivered -> cancelled) - should return 400
curl -X PUT http://localhost:8000/orders/<order_id>/status \
  -H "Content-Type: application/json" \
  -H "X-User-ID: user-123" \
  -d '{"status": "cancelled"}'
```

**Step 6: List orders**
```bash
# All orders for this user
curl http://localhost:8000/orders/ -H "X-User-ID: user-123"

# Filter by status
curl "http://localhost:8000/orders/?status=delivered" -H "X-User-ID: user-123"

# Paginate
curl "http://localhost:8000/orders/?page=1&limit=5" -H "X-User-ID: user-123"

# Try to access another user's order (should return 404)
curl http://localhost:8000/orders/<order_id> -H "X-User-ID: different-user"
```

---

## 4. Complete End-to-End Scenario

This reproduces a realistic user journey from browse to delivered order.

```bash
BASE=http://localhost:8000

# 1. Health check
curl $BASE/health

# 2. Browse products
curl "$BASE/products/?category=Men&limit=5"

# 3. Search for a specific item
curl "$BASE/search/?q=Oxford shirt"

# 4. Get a specific product (copy its _id)
PRODUCT_ID=<paste_id_here>
curl $BASE/products/$PRODUCT_ID

# 5. Check inventory
curl $BASE/inventory/$PRODUCT_ID

# 6. Add to cart
curl -X POST $BASE/cart/items \
  -H "Content-Type: application/json" \
  -H "X-User-ID: demo-user" \
  -d "{\"product_id\": \"$PRODUCT_ID\", \"quantity\": 2}"

# 7. View cart (verify subtotal = price * 2)
curl $BASE/cart/ -H "X-User-ID: demo-user"

# 8. Place order
ORDER=$(curl -s -X POST $BASE/orders/ \
  -H "Content-Type: application/json" \
  -H "X-User-ID: demo-user" \
  -d '{"shipping_address": "42 Demo Lane, Bangalore 560001"}')
echo $ORDER
ORDER_ID=$(echo $ORDER | python -c "import sys,json; print(json.load(sys.stdin)['_id'])")

# 9. Cart should now be empty
curl $BASE/cart/ -H "X-User-ID: demo-user"

# 10. Inventory should be decremented by 2
curl $BASE/inventory/$PRODUCT_ID

# 11. Advance to delivered
curl -X PUT $BASE/orders/$ORDER_ID/status -H "Content-Type: application/json" -H "X-User-ID: demo-user" -d '{"status":"confirmed"}'
curl -X PUT $BASE/orders/$ORDER_ID/status -H "Content-Type: application/json" -H "X-User-ID: demo-user" -d '{"status":"shipped"}'
curl -X PUT $BASE/orders/$ORDER_ID/status -H "Content-Type: application/json" -H "X-User-ID: demo-user" -d '{"status":"delivered"}'

# 12. Final order state
curl $BASE/orders/$ORDER_ID -H "X-User-ID: demo-user"
```

---

## 5. Testing with the Seeded Users

After running `python scripts/seed_database.py`, three users have pre-existing orders:

| User ID         | Orders                        |
|-----------------|-------------------------------|
| `seed-user-001` | 1 delivered + 1 pending       |
| `seed-user-002` | 1 shipped + 1 confirmed       |
| `seed-user-003` | 1 cancelled + 1 pending       |

```bash
# View seed-user-001's orders
curl http://localhost:8000/orders/ -H "X-User-ID: seed-user-001"

# View seed-user-002's shipped order
curl "http://localhost:8000/orders/?status=shipped" -H "X-User-ID: seed-user-002"
```

Three products are intentionally low-stock (will appear in `/inventory/low-stock`):
- `MEN-POLO-001` (qty: 7)
- `WOM-KURTA-001` (qty: 5)
- `ACC-SCARF-001` (qty: 3)

```bash
curl "http://localhost:8000/inventory/low-stock?threshold=10"
```

---

## 6. Error Cases to Verify

| Scenario | Expected Response |
|----------|------------------|
| Create product with duplicate SKU | `409 Conflict`, `error: duplicate_sku` |
| Get product with invalid ID | `404 Not Found`, `error: product_not_found` |
| Add inactive product to cart | `422 Unprocessable`, `error: inactive_product` |
| Add more items than stock | `422 Unprocessable`, `error: insufficient_stock` |
| Place order with empty cart | `400 Bad Request`, `error: validation_error` |
| Invalid status transition | `400 Bad Request`, `error: invalid_status_transition` |
| Access another user's order | `404 Not Found` (intentional: no 403 disclosure) |
| Missing X-User-ID header | `422 Unprocessable` (FastAPI validation) |
| Deduct inventory below zero | `422 Unprocessable`, `error: insufficient_stock` |

---

## 7. Docker Testing

```bash
# Start services
docker compose up --build -d

# Wait for health checks to pass (~20 seconds)
docker compose ps

# Run all tests inside the container (against local MongoDB)
# Note: tests run against localhost, not the container — run locally instead
pytest

# Seed inside the container
docker compose exec api python scripts/seed_database.py

# Test the containerised API
curl http://localhost:8000/health
curl http://localhost:8000/docs  # open in browser

# View API logs
docker compose logs -f api

# View MongoDB logs
docker compose logs -f mongo

# Tear down
docker compose down
```
