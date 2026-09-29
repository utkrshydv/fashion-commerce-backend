# Learning Log — Fashion Commerce Backend

> This document is a personal study guide for this repository.
> Every stage appends a new section explaining the actual code that was written,
> the reasoning behind it, and what you should be able to explain in an interview.

---

## Stage 0: Architecture & Project Setup

### What We Built

In this stage we created the structural foundation of the project — no business logic yet,
just the skeleton and the thinking behind every major decision.

**Files created:**
```
app/
├── main.py                         ← App factory + lifespan handler
├── api/routes/health.py            ← Health check endpoint
├── core/
│   ├── config.py                   ← Pydantic Settings configuration
│   ├── exceptions.py               ← Custom exception hierarchy
│   └── logging.py                  ← Centralized logging setup
├── db/
│   ├── client.py                   ← MongoDB connection lifecycle
│   └── indexes.py                  ← All index definitions
├── models/        (placeholders)
├── schemas/       (placeholders)
├── repositories/  (placeholders)
├── services/      (placeholders)
└── utils/

tests/
scripts/
requirements.txt
pyproject.toml
Dockerfile
docker-compose.yml
.env.example
.gitignore
README.md
```

---

### Why We Built It This Way

We built the skeleton before any business logic because architecture decisions made early
are hard to undo later. If you start by writing product routes, you tend to push everything
into a single file. Once the project is planned as a layered system from the beginning,
each new feature has a natural place to live.

---

### How the Layered Architecture Works

This project uses a **layered (onion) architecture**. Think of it as a strict rule:
each layer can only talk to the layer directly below it.

```
HTTP Request
     │
     ▼
┌─────────────────────────────┐
│  Router / Route Handler     │  app/api/routes/
│  (What does the HTTP say?)  │
└─────────────┬───────────────┘
              │ calls
              ▼
┌─────────────────────────────┐
│  Service / Business Logic   │  app/services/
│  (What should we do?)       │
└─────────────┬───────────────┘
              │ calls
              ▼
┌─────────────────────────────┐
│  Repository / Data Access   │  app/repositories/
│  (How do we get/store it?)  │
└─────────────┬───────────────┘
              │ queries
              ▼
         MongoDB
```

**What each layer is responsible for:**

| Layer | Lives in | Responsibility |
|-------|----------|----------------|
| Router | `app/api/routes/` | Parse HTTP request, call service, return HTTP response |
| Service | `app/services/` | Business rules, validation logic, orchestration |
| Repository | `app/repositories/` | MongoDB queries only — no business rules |
| Database | MongoDB | Persistence |

**Why this separation matters:**

- If you want to change from MongoDB to PostgreSQL later, you only change the repository.
  The service layer doesn't need to know.
- If you want to test business logic (e.g., does the cart correctly calculate the total?),
  you can test the service layer with a fake/mock repository — no real database needed.
- If the HTTP API contract changes (REST → GraphQL), only the router changes.
  The service layer doesn't need to know.

---

### What a Router Does (and Doesn't Do)

The router in `app/api/routes/products.py` (Stage 2) will:
- Accept an HTTP POST request for creating a product
- Parse and validate the request body using a Pydantic schema
- Call `ProductService.create_product()`
- Return a 201 response with the created product

The router will **not**:
- Check if a SKU is a duplicate (that's business logic → Service)
- Query MongoDB directly (that's data access → Repository)
- Calculate the final price after discount (that's business logic → Service)

A simple test: if a function in a route handler would still make sense even if there were
no HTTP involved (e.g., in a CLI script or a background task), that logic belongs in the
Service layer, not the router.

---

### What a Service Does

`app/services/product_service.py` (Stage 2) will:
- Receive a "create product" request from the router
- Check if a product with the same SKU already exists (via repository)
- Raise a `DuplicateSKUException` if so
- Calculate `final_price = price * (1 - discount_percentage / 100)`
- Call `ProductRepository.insert_one()` with the complete document
- Return the created product

The service coordinates the business flow. It doesn't know about HTTP status codes.
It only knows about domain rules.

---

### What a Repository Does

`app/repositories/product_repository.py` (Stage 2) will:
- Contain pure database access methods: `find_one`, `find_many`, `insert_one`, `update_one`, `delete_one`
- Accept Python dicts or typed documents
- Return raw MongoDB documents (or `None` if not found)
- Wrap unexpected database exceptions in `DatabaseException`

A repository method has no `if` statements about business rules.
It just asks MongoDB for data and returns it.

---

### Why Business Logic Must Not Live in Routers

Imagine you have an order creation route:

```python
# BAD — logic directly in router
@router.post("/orders/{user_id}")
async def create_order(user_id: str, db = Depends(get_database)):
    cart = await db["carts"].find_one({"user_id": user_id})
    if not cart or not cart["items"]:
        raise HTTPException(status_code=400, detail="Cart is empty")
    # ... 50 more lines of business logic
```

Problems:
1. You can't test the order creation logic without making an HTTP request.
2. If you need to create an order from a background task (not an HTTP endpoint), you'd have to duplicate all this logic.
3. As the logic grows, the route handler becomes impossible to read.

With a service layer:
```python
# GOOD — thin router
@router.post("/orders/{user_id}")
async def create_order(user_id: str, service = Depends(get_order_service)):
    order = await service.create_order(user_id)
    return order
```

The service handles the business logic. The router just translates HTTP → service call → HTTP.

---

### Configuration: `app/core/config.py`

**How it works:**

`Settings` is a Pydantic Settings class. When you call `get_settings()`:
1. Pydantic reads your `.env` file (if it exists).
2. Pydantic checks actual environment variables (these win over .env file values).
3. Pydantic validates and type-coerces all values.
4. If a required field is missing or has the wrong type, the app raises an error immediately
   on startup — you never get a running server with a missing database URI.

`@lru_cache(maxsize=1)` on `get_settings()` means the `.env` file is parsed exactly once
per process lifetime, no matter how many times `get_settings()` is called.

**Why this matters for dependency injection:**

In FastAPI, you can write:
```python
from app.core.config import get_settings
from fastapi import Depends

async def some_route(settings = Depends(get_settings)):
    ...
```

FastAPI will call `get_settings()` (which returns the cached instance) and inject it.
In tests, you can override this dependency to inject test-specific settings.

---

### Exception Hierarchy: `app/core/exceptions.py`

**The problem it solves:**

Without a custom exception hierarchy, you'd either:
a) Raise `HTTPException` directly inside services (the service now knows about HTTP — wrong layer), or
b) Catch every possible error in every route handler and convert it (massive duplication).

**Our solution:**

```
AppException (base)
├── ValidationException (400)
├── InvalidQuantityException (400)
├── InvalidStatusTransitionException (400)
├── NotFoundException (404)
│   ├── ProductNotFoundException
│   ├── CartNotFoundException
│   ├── OrderNotFoundException
│   └── InventoryNotFoundException
├── DuplicateSKUException (409)
├── InsufficientStockException (422)
├── InactiveProductException (422)
└── DatabaseException (500)
```

The service raises `ProductNotFoundException`. The router never catches it.
The **global exception handler** in `main.py` catches it and converts it to a
consistent JSON response:

```json
{
  "error": "product_not_found",
  "message": "Product with id '...' does not exist."
}
```

This means:
- Every error in the application returns the same JSON shape.
- Services stay clean — they raise domain errors, not HTTP errors.
- You add the handler once in `main.py`, not in every route.

---

### Database Client: `app/db/client.py`

**The pattern:**

```python
_client: Optional[AsyncMongoClient] = None
_database: Optional[AsyncDatabase] = None

async def connect_to_mongo() -> None:
    global _client, _database
    _client = AsyncMongoClient(settings.mongodb_uri)
    _database = _client[settings.mongodb_database]
    await _client.admin.command("ping")  # Verify connection before serving traffic

def get_database() -> AsyncDatabase:
    if _database is None:
        raise RuntimeError("Not connected")
    return _database
```

**Why not just import `_database` directly in each repository?**

If you import a module-level variable directly, tests can't easily replace it
with a test database. With `get_database()` as a FastAPI dependency:

```python
async def some_route(db = Depends(get_database)):
    ...
```

In tests, you can override `get_database` to return a test database:
```python
app.dependency_overrides[get_database] = lambda: test_db
```

This is **dependency injection** — instead of a function creating or importing
its own dependencies, they are provided to it from outside.

**Why PyMongo Async instead of Motor?**

Motor is an async wrapper around PyMongo that was necessary before PyMongo added
native async support. Since PyMongo 4.5+, `AsyncMongoClient` is built in.
Using Motor adds a dependency with no benefit and an extra abstraction layer.
We use `AsyncMongoClient` from PyMongo directly — fewer dependencies, same capability.

---

### MongoDB Collection Design

**Collections planned:**

| Collection | Purpose |
|------------|---------|
| `products` | Product catalog documents |
| `inventory` | Stock levels, one document per product |
| `carts` | Shopping cart, one document per user |
| `orders` | Order history |

**Why separate `products` and `inventory`?**

Option A — Store stock inside the product document:
```json
{ "name": "...", "price": 499, "stock_quantity": 50 }
```

Option B — Separate collections:
```json
// products: { "name": "...", "price": 499 }
// inventory: { "product_id": "...", "quantity": 50 }
```

We chose Option B. Reasons:
- Stock changes frequently (every order, every restock). Product metadata changes rarely.
  Keeping them separate means high-frequency writes to `inventory` don't touch the product document.
- In production, inventory often has additional fields (warehouse location, reserved quantity,
  batch tracking) that belong separately.
- The inventory service can be developed and tested independently.

**Why store a price snapshot in orders?**

```json
// order item
{
  "product_id": "...",
  "name": "Blue Denim Jacket",
  "purchase_price": 1299.00,   ← snapshot at time of purchase
  "quantity": 2
}
```

If you reference the current product price when displaying an old order, the displayed
price will change whenever the product price changes. Customers need to see what they
actually paid. We store the price at purchase time.

**Cart document design:**
```json
{
  "user_id": "user_123",
  "items": [
    {
      "product_id": "...",
      "name": "...",
      "price": 999.00,
      "quantity": 2
    }
  ],
  "updated_at": "2024-01-15T..."
}
```

One cart per user. We upsert (insert if missing, update if exists) by `user_id`.
The `user_id_unique` index enforces this constraint at the database level.

---

### Index Strategy

**Defined in `app/db/indexes.py`:**

| Index | Collection | Type | Justifies |
|-------|-----------|------|-----------|
| `sku_unique` | products | Unique | Enforces SKU uniqueness, fast lookup by SKU |
| `category_price` | products | Compound | Filter by category, sort by price — most common catalog query |
| `brand` | products | Single | Brand filter in catalog and search |
| `status` | products | Single | Filter active/inactive products |
| `price` | products | Single | Price range queries |
| `created_at_desc` | products | Single (desc) | Newest-first default sort |
| `text_search` | products | Text | Full-text search on name + brand + description |
| `user_id_created_at` | orders | Compound | "My orders" query — by user, newest first |
| `status` | orders | Single | Admin/ops filtering by order status |
| `user_id_unique` | carts | Unique | One cart per user, fast lookup |
| `product_id_unique` | inventory | Unique | One inventory record per product |
| `quantity` | inventory | Single | Low-stock monitoring queries |

**The tradeoff of adding indexes:**

Every index you add speeds up reads but slows down writes (because MongoDB must update
the index whenever a document is inserted, updated, or deleted). It also uses disk space.
We only added indexes for fields that appear in actual WHERE clauses, sorts, or lookups.
We didn't index every field "just in case."

---

### Application Startup Flow

When you run `uvicorn app.main:app`:

1. Python imports `app.main` and calls `create_app()`.
2. `create_app()` constructs the FastAPI instance with the `lifespan` context manager.
3. Uvicorn calls the `lifespan` async generator.
4. `configure_logging()` sets up the log format.
5. `connect_to_mongo()` creates the `AsyncMongoClient` and pings MongoDB.
   If this fails, the application exits before serving any requests.
6. `ensure_indexes()` creates all collection indexes (idempotently — safe to call every restart).
7. The `yield` statement suspends the lifespan generator — the application is now running.
8. Uvicorn starts accepting HTTP requests.
9. On shutdown (Ctrl+C or SIGTERM), the code after `yield` runs.
10. `close_mongo_connection()` closes the client cleanly.

This is the **lifespan context manager pattern** introduced in FastAPI 0.93.
It replaces the older `@app.on_event("startup")` / `@app.on_event("shutdown")` decorators.

---

### How Docker Fits In

**Dockerfile:**
- Starts from `python:3.12-slim` (small base image).
- Copies `requirements.txt` first, then installs dependencies.
  This is deliberate: Docker caches image layers. If only application code changes
  (not requirements.txt), Docker reuses the cached dependency layer and rebuilds in seconds.
- Copies application source.
- Runs Uvicorn.

**docker-compose.yml:**
- `mongo` service: uses the official MongoDB 7 image, mounts a named volume (`mongo_data`)
  so data persists across container restarts.
- `api` service: builds from our Dockerfile, waits for `mongo` to pass its health check
  before starting (`depends_on: mongo: condition: service_healthy`).
- The `api` service sets `MONGODB_URI=mongodb://mongo:27017` — "mongo" is the Docker
  Compose service name, which acts as a hostname inside the Docker network.
  On your host machine, "localhost:27017" reaches Mongo. Inside Docker, "mongo:27017" reaches it.

**Why persistent volumes?**

Without a volume, every time you run `docker compose down && docker compose up`, MongoDB
starts fresh with no data. The `mongo_data` named volume keeps data between restarts.
`docker compose down -v` removes volumes if you want a clean slate.

---

### Testing Strategy (Preview)

Tests will be in two categories:

**Unit tests** (`tests/unit/`):
- Test service methods in isolation.
- Use mock/fake repositories — no real database.
- Example: `test_cart_service.py` tests that adding a product calculates the subtotal correctly.
- Fast — no I/O.

**Integration tests** (`tests/integration/`):
- Start a real FastAPI app (using `httpx.AsyncClient` with `ASGITransport`).
- Connect to a real MongoDB test database (isolated from dev data).
- Test the full request → response path.
- Example: POST /products → verify document in DB → GET /products → verify response.
- Slower but prove the whole system works.

The test database name (`TEST_MONGODB_DATABASE`) is different from the dev database.
The `conftest.py` fixture creates the test app with the test database and drops all
collections after each test to keep tests isolated.

---

### Important Decisions Made in Stage 0

**Decision: PyMongo Async over Motor**

Motor was the standard async MongoDB library before PyMongo 4.5 added native async support.
Motor is now a thin wrapper that adds a dependency with no benefit. We use `AsyncMongoClient`
from PyMongo directly.

**Decision: Separate `inventory` collection**

Stock quantity lives in `inventory`, not inside the product document. This separates
high-frequency write operations (inventory changes) from product metadata reads.

**Decision: Modular monolith, not microservices**

A microservices architecture would split products, orders, inventory into separate services
with separate databases and message queues. That complexity is unjustified for a single-team
portfolio project. A modular monolith gives clean module boundaries while running as a
single process.

**Decision: Application factory pattern (`create_app()`)**

`main.py` exposes a `create_app()` function, not just a module-level `app = FastAPI()`.
This allows tests to call `create_app()` to get a fresh application instance with test
configuration — without affecting the production instance.

**Decision: Global exception handler instead of HTTPException in services**

Services raise `AppException` subclasses. The global handler in `main.py` converts them
to HTTP responses. This keeps services unaware of HTTP and makes error responses consistent.

---

### Questions I Should Be Able to Answer Before Stage 1

**Why do we have a service layer?**
Because business logic (SKU uniqueness check, price calculation, stock validation,
status transition rules) should not live in route handlers. The service layer is the
place where the actual "what should the system do?" decisions are made. This makes
logic testable without HTTP, and reusable from background tasks or scripts.

**Why do we have a repository layer?**
So that database query details are isolated in one place. If you want to change a
query (e.g., add a new index and update the filter), you change one repository method.
The service above it doesn't need to change. It also allows you to mock/replace the
repository in unit tests.

**Why shouldn't a route directly query MongoDB?**
Because the route's job is to translate HTTP to Python and Python to HTTP. If it also
queries MongoDB, it's doing three different things — HTTP handling, business logic, and
data access. That's three separate reasons to change a single function, which violates
the Single Responsibility Principle.

**What is dependency injection?**
Dependency injection means a function receives its dependencies from outside rather than
creating them itself. In FastAPI: `async def route(db = Depends(get_database))` — the
route doesn't create the database connection; FastAPI calls `get_database()` and injects
the result. This makes the function testable because you can inject a different value in tests.

**What does asynchronous I/O mean?**
When your code makes a database query, it has to wait for MongoDB to respond. In a synchronous
system, the Python thread blocks — it does nothing while waiting. In an asynchronous system
(using `async/await`), the Python event loop runs other coroutines while waiting for the
database. A single-threaded async FastAPI server can handle many simultaneous requests because
it's never blocked — it's always either working or handing off to the event loop to handle
something else.

**Why use indexes in MongoDB?**
Without an index, MongoDB must read every document in a collection to find matching ones
(a "collection scan"). With an index on `category`, MongoDB can jump directly to documents
in a specific category. On a collection of 1 million products, the difference is the
response time being milliseconds vs. seconds.

**What problem does Docker solve?**
"It works on my machine" — Docker packages your application, its runtime (Python 3.12),
and its environment into a container that runs identically on any machine. `docker-compose.yml`
also defines the entire local development environment (MongoDB + API) so a new developer
can run `docker compose up` and have a working system in minutes, without installing MongoDB
or Python locally.

**What is the lifespan context manager?**
It's an `async` generator (uses `yield`) that FastAPI calls on startup (code before `yield`)
and on shutdown (code after `yield`). We use it to connect to MongoDB, create indexes,
and close the connection cleanly. It replaced the older `@app.on_event` decorator pattern.

**What is Pydantic Settings?**
A Pydantic extension that reads configuration from environment variables and `.env` files
and validates/coerces their types. If `API_PORT=abc` is in the environment and the schema
says `api_port: int`, Pydantic raises an error at startup rather than crashing later with
a confusing type error.

**Why does the global exception handler exist?**
So we never scatter `HTTPException(status_code=...)` throughout services and repositories.
Instead, services raise typed domain exceptions (`ProductNotFoundException`,
`InsufficientStockException`). The handler in `main.py` converts them to consistent JSON.
One place to change the error format. Services stay decoupled from HTTP.

---

### Key Takeaway for Stage 0

Before writing a single line of business logic, we established:
- Where every kind of code lives (routers, services, repositories)
- How the database connection is managed (singleton, dependency injection)
- How errors flow from domain to HTTP (custom exceptions + global handler)
- What indexes the database will need (defined upfront, based on known query patterns)
- How the application starts and stops (lifespan context manager)
- How configuration is loaded and validated (Pydantic Settings)

This foundation means every Stage 1–10 feature has a clear, consistent place to go.
You won't be making architectural decisions while implementing features — those are
already made.

---
