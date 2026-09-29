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

---

## Stage 1: FastAPI Foundation + Configuration + MongoDB Connection + Lifecycle + Health Check

### What We Built

Stage 1 made the scaffold from Stage 0 actually run end-to-end. Everything before this stage existed as code but had never been executed as a real server.

**Files created/modified:**

| File | Change |
|------|--------|
| `.env` | New — local development environment variables |
| `requirements.txt` | Fixed — removed deprecated `[srv]` extra from pymongo |
| `app/db/client.py` | Hardened — added `serverSelectionTimeoutMS`, made `close()` properly awaited |
| `app/main.py` | Improved — added `RuntimeError` handler, removed duplicate import, added `openapi_tags` |
| `app/api/routes/health.py` | Fixed — `settings` now injected via `Depends(get_settings)` instead of direct call |
| `tests/conftest.py` | New — full test fixture infrastructure |
| `tests/integration/test_health.py` | New — 7 integration tests for GET /health |
| `tests/unit/test_config.py` | New — 11 unit tests for Settings |
| `tests/unit/test_exceptions.py` | New — 37 unit tests for exception hierarchy |

**Test result: 55 passed, 0 failed, 0 warnings.**

---

### Why We Built It This Way

Stage 0 was architecture. Stage 1 is the proof that it works. Before writing any business logic (products, orders, etc.), we need to be absolutely certain that:
- The server starts cleanly
- MongoDB connects and indexes are created
- The health endpoint responds correctly
- Tests can run against the real codebase without touching the dev database

Everything built in Stage 1 is infrastructure that every future stage depends on.

---

### How It Works: Full Startup Sequence

When you run `uvicorn app.main:app`:

```
1. Python imports app.main
2. create_app() builds the FastAPI instance
3. Middleware (CORS) is registered
4. Exception handlers are registered (AppException, RuntimeError)
5. health.router is included
6. Module-level `app = create_app()` is assigned
7. Uvicorn calls the lifespan(app) async generator
8. configure_logging() sets up the log formatter
9. get_settings() reads .env → returns Settings(app_env="development", ...)
10. connect_to_mongo() creates AsyncMongoClient(uri, serverSelectionTimeoutMS=5000)
11. client.admin.command("ping") verifies MongoDB is reachable (fails fast in 5s if not)
12. get_database() returns the handle
13. ensure_indexes(db) runs create_index() on all 4 collections (idempotent)
14. yield — server is live, accepting requests
15. On Ctrl+C/SIGTERM: close_mongo_connection() → await _client.close()
```

The actual log output from our run:
```
INFO | app.main      | Starting Fashion Commerce Backend v0.1.0 [env=development]
INFO | app.db.client | Connecting to MongoDB at mongodb://localhost:27017
INFO | app.db.client | MongoDB connected — database: fashion_commerce (timeout: 5000ms)
INFO | app.db.indexes| Product indexes ensured.
INFO | app.db.indexes| Order indexes ensured.
INFO | app.db.indexes| Cart indexes ensured.
INFO | app.db.indexes| Inventory indexes ensured.
INFO | app.db.indexes| All MongoDB indexes ensured.
INFO | app.main      | Application startup complete — ready to serve requests.
```

---

### How a Request Flows Through GET /health

```
httpx/browser: GET http://localhost:8000/health
    │
    ▼
Uvicorn (ASGI server)
    │ parses HTTP, calls the ASGI app
    ▼
FastAPI routing
    │ matches "/health" → health_check()
    ▼
FastAPI dependency resolution
    │ Depends(get_database) → calls get_database() → returns _database handle
    │ Depends(get_settings) → calls get_settings() → returns cached Settings
    ▼
health_check(db=<AsyncDatabase>, settings=<Settings>)
    │ await db.command("ping") → MongoDB responds { ok: 1 }
    │ db_status = "ok"
    │ returns {"status": "ok", "version": "0.1.0", "environment": "development", "database": "ok"}
    ▼
FastAPI serializes dict → JSON response body
    ▼
HTTP 200 {"status": "ok", "version": "0.1.0", ...}
```

---

### The `serverSelectionTimeoutMS` Fix

**Before Stage 1:** If MongoDB was down when the server started, PyMongo would wait 30 seconds before raising an error. The server appeared to hang with no log output.

**After Stage 1:** We pass `serverSelectionTimeoutMS=5_000` to `AsyncMongoClient`. If MongoDB is unreachable, the startup `ping` command fails in ≤5 seconds with a clear error message. Uvicorn logs it and exits instead of silently hanging.

This is the difference between:
```
# Bad: no output for 30 seconds, then cryptic crash
uvicorn app.main:app
[30 seconds of silence...]
ERROR: Application startup failed.
```

and:
```
# Good: immediate, clear failure
INFO | Connecting to MongoDB at mongodb://localhost:27017
ERROR | ServerSelectionTimeoutError after 5s — check MONGODB_URI
```

---

### Why Settings Must Be a FastAPI Dependency

**The bug we found and fixed:**

The original `health_check()` called `get_settings()` directly:
```python
# BEFORE (broken for tests)
async def health_check(db = Depends(get_database)):
    settings = get_settings()          # called directly
    return {"environment": settings.app_env, ...}
```

In tests, we set `app.dependency_overrides[get_settings] = lambda: test_settings`.
FastAPI's `dependency_overrides` only intercepts calls that go through its `Depends()` system.
A direct `get_settings()` call bypasses it entirely.

So the test saw `environment="development"` instead of `"testing"` — the override had no effect.

**The fix:**
```python
# AFTER (correct)
async def health_check(
    db: AsyncDatabase = Depends(get_database),
    settings: Settings = Depends(get_settings),  # injected, not called directly
):
    return {"environment": settings.app_env, ...}
```

**Rule to remember:** Any value that a test might need to override must be received through `Depends()`, not fetched directly inside the function. This applies to settings, database handles, authentication tokens, external service clients — anything that varies between environments.

---

### The Event Loop Problem in Tests (and How We Solved It)

**The bug we found:**

Our first version of `conftest.py` created the `AsyncMongoClient` at session scope:
```python
@pytest_asyncio.fixture(scope="session")
async def mongo_client(test_settings):
    mc = AsyncMongoClient(...)  # created in the session event loop
    yield mc
```

pytest-asyncio (with `asyncio_mode="auto"`) creates a **new event loop for each test function**. PyMongo's `AsyncMongoClient` binds internally to the event loop it was created on. When a test function's loop tried to use a client created in the session's loop, it raised:

```
RuntimeWarning: Cannot use AsyncMongoClient in different event loop.
AsyncMongoClient uses low-level asyncio APIs that bind it to the event loop it was created on.
```

**The fix:** Make the `db` fixture function-scoped. Each test function creates its own `AsyncMongoClient` in its own event loop, uses it, then closes it.

```python
@pytest_asyncio.fixture(scope="function")   # ← function scope, not session
async def db(test_settings: Settings) -> AsyncDatabase:
    mc = AsyncMongoClient(...)    # same event loop as the test
    ...
    yield database
    await mc.close()              # same event loop closes it
```

Performance impact: each test now does one MongoDB connection + ping (~1ms). For 55 tests, this adds about 50ms total. Completely acceptable.

**Rule to remember:** In async Python, objects that hold internal references to an event loop must be created and destroyed in the same loop. When in doubt, use function scope for async resources in pytest.

---

### Why `mc.close()` Must Be Awaited

During the first run, we got:
```
RuntimeWarning: coroutine 'AsyncMongoClient.close' was never awaited
```

In PyMongo 4.18, `AsyncMongoClient` is fully async, including its `close()` method. Calling it without `await` creates a coroutine object but never executes it — the connection is never actually closed.

```python
mc.close()        # WRONG: schedules close but doesn't run it
await mc.close()  # CORRECT: actually closes the connection
```

We fixed this in both `tests/conftest.py` (test fixture) and `app/db/client.py` (production shutdown handler).

---

### How the Test Infrastructure Works

**conftest.py creates three fixtures:**

1. **`test_settings`** (session scope):
   - Constructs `Settings(app_env="testing", mongodb_database="fashion_commerce_test", ...)`
   - Created once for the entire test session
   - No event loop dependency — just a Python object

2. **`db`** (function scope):
   - Creates a fresh `AsyncMongoClient` per test (same event loop)
   - Runs `ensure_indexes()` so all tests start with indexes in place
   - `yield`s the `AsyncDatabase` handle
   - Awaits `mc.close()` after the test
   - Use this to seed data or inspect the DB directly

3. **`client`** (function scope):
   - Calls `create_app()` fresh for each test
   - Overrides `get_database → lambda: db` (injects the test DB)
   - Overrides `get_settings → lambda: test_settings` (injects test config)
   - Wraps in `httpx.AsyncClient(transport=ASGITransport(app))` — no real TCP port
   - Use this to make HTTP requests in integration tests

**What `ASGITransport` does:**

Instead of binding a real port and sending HTTP bytes over TCP, `ASGITransport` feeds requests directly into the FastAPI ASGI callable. The full middleware, routing, exception handling, and dependency injection stack runs — just without the network layer. Tests are faster and don't need `httpx` to find an open port.

---

### What `dependency_overrides` Does

FastAPI maintains a dict on the app object:
```python
app.dependency_overrides: dict[Callable, Callable]
```

When FastAPI resolves a dependency like `Depends(get_database)`, it checks `dependency_overrides` first:
- If `get_database` is a key in `dependency_overrides`, it calls the override instead.
- Otherwise, it calls the real `get_database`.

In tests:
```python
app.dependency_overrides[get_database] = lambda: db     # lambda returns the test DB
app.dependency_overrides[get_settings] = lambda: test_settings  # lambda returns test config
```

Every route that uses `Depends(get_database)` or `Depends(get_settings)` now gets the test values. The real `get_database()` function (which checks `_database is None`) is never called — so we don't need the lifespan to have run.

This is why the rule "use Depends() for anything that varies between environments" is so important: only things that go through Depends() can be overridden.

---

### Bug Inventory for Stage 1

| Bug | Root cause | Fix |
|-----|-----------|-----|
| Server hangs 30s on bad Mongo URI | Default `serverSelectionTimeoutMS=30000` | Set to `5000` in `AsyncMongoClient(...)` |
| Test `environment` was `"development"` not `"testing"` | `get_settings()` called directly, bypassing `dependency_overrides` | Pass `settings` via `Depends(get_settings)` |
| `RuntimeWarning: cannot use AsyncMongoClient in different event loop` | Session-scoped client shared across per-function event loops | Made `db` fixture function-scoped |
| `RuntimeWarning: coroutine ... was never awaited` | `mc.close()` called without `await` (pymongo 4.18 close is async) | `await mc.close()` in conftest and client.py |

---

### Important Concepts from Stage 1

**ASGI (Asynchronous Server Gateway Interface):**
ASGI is the protocol that connects Python web frameworks (FastAPI, Django async, Starlette) to async-capable web servers (Uvicorn, Hypercorn). It defines how the server calls the framework and how the framework returns responses. Uvicorn is the ASGI *server*; FastAPI is the ASGI *application*. `ASGITransport` in httpx lets tests call the ASGI application directly, without a server.

**Why Uvicorn and not Gunicorn alone?**
Gunicorn is a WSGI server (synchronous). FastAPI is async and uses the ASGI interface. Uvicorn is the standard ASGI server for FastAPI. In production, you often see `gunicorn -k uvicorn.workers.UvicornWorker` — Gunicorn manages multiple Uvicorn worker processes for multi-core CPU utilization, while each worker runs the async event loop.

**What is `asynccontextmanager`?**
`@asynccontextmanager` turns an async generator function into a context manager. The `yield` is the boundary: code before it runs on `__aenter__` (startup), code after it runs on `__aexit__` (shutdown). FastAPI calls the lifespan generator with `async with` internally — everything before `yield` runs at startup, everything after at shutdown.

**Why does `lru_cache` matter for `get_settings()`?**
`Settings()` reads and parses the `.env` file and all environment variables every time it's called. With `@lru_cache(maxsize=1)`, parsing happens exactly once per process. Every subsequent call to `get_settings()` returns the cached object in nanoseconds. Without it, reading a `.env` file for every incoming request would add measurable latency under load.

---

### Interview Questions for Stage 1

1. **What is ASGI and how is it different from WSGI?**
   WSGI is synchronous — one request blocks the worker thread until the response is returned. ASGI is async — one worker can handle thousands of concurrent requests by yielding control to the event loop while waiting for I/O (database, network). FastAPI requires ASGI; Flask uses WSGI by default.

2. **What does `serverSelectionTimeoutMS` control in PyMongo?**
   When PyMongo needs to run a command, it tries to select a suitable MongoDB server from the topology. If no server is available (wrong URI, server down), `serverSelectionTimeoutMS` controls how long it waits before raising `ServerSelectionTimeoutError`. Default is 30 seconds. We set it to 5 to fail fast.

3. **What is dependency injection in FastAPI?**
   Instead of functions fetching their own dependencies (calling `get_settings()` or creating their own database connections), FastAPI creates and injects the dependencies. `Depends(get_database)` tells FastAPI: "call `get_database()` and pass the result as this argument." Tests can substitute fake implementations via `dependency_overrides`.

4. **Why are your test fixtures function-scoped and not session-scoped?**
   Because pytest-asyncio creates a new event loop per test function, and `AsyncMongoClient` binds to the loop it was created in. A session-scoped client would be created in the session's loop but used from per-function loops — causing a runtime error. Function-scoped fixtures create and close the client within the same event loop.

5. **What does `ASGITransport` do in httpx?**
   It lets httpx send requests directly into an ASGI application callable, bypassing the network entirely. The full FastAPI middleware, routing, dependency injection, and exception handling runs, but no TCP port is opened. Tests are faster, more reliable (no port conflicts), and don't require the server to be running separately.

6. **What happens if `connect_to_mongo()` fails during startup?**
   The exception propagates out of the lifespan generator's startup block. FastAPI/Uvicorn catches it, logs the error, and exits the process. The server never starts serving traffic. This is correct: a server that can't reach its database should not pretend to be healthy.

7. **How does the global exception handler in `main.py` work?**
   `@app.exception_handler(AppException)` registers a handler for any exception that is a subclass of `AppException`. FastAPI catches the exception before returning a 500, calls the handler, and returns the handler's `JSONResponse` instead. Services never need to know about HTTP status codes — they raise typed domain exceptions, and the handler converts them in one place.

8. **Why does every route use `Depends(get_settings)` instead of calling `get_settings()` directly?**
   `dependency_overrides` only intercepts calls that go through the FastAPI dependency system. A direct call bypasses the override and always returns the production settings — even in tests. To make a function's dependencies replaceable in tests, they must come through `Depends()`.

---

### Things I Should Be Able to Explain Before Stage 2

- [ ] How the FastAPI lifespan context manager works (startup → yield → shutdown)
- [ ] What ASGI is and why Uvicorn is needed
- [ ] How `dependency_overrides` makes tests possible without mocking
- [ ] Why `serverSelectionTimeoutMS` matters and what happens without it
- [ ] Why `AsyncMongoClient.close()` must be awaited in pymongo 4.18
- [ ] Why the event loop scope of async fixtures must match the test function scope
- [ ] The difference between `@lru_cache` on `get_settings()` and calling `Settings()` each time
- [ ] How `ASGITransport` differs from making HTTP requests to a running server
- [ ] Why services should raise `AppException` subclasses instead of `HTTPException`

---

### Key Takeaway for Stage 1

Stage 1 proved the architecture works. We found and fixed four real bugs — none of them would have been obvious without actually running the code and tests. The most important insight: **async Python has strict event loop ownership rules**. An `AsyncMongoClient` belongs to the loop that created it. Violating this rule causes runtime errors that are hard to diagnose if you don't understand the underlying mechanism. All of our test fixtures are now scoped correctly, and the reason is documented so you can explain it in an interview.

---

---

## Stage 2: Product Catalog CRUD

### What Was Built

A complete four-layer product catalog: schemas → repository → service → router.

| Layer | File | Responsibility |
|-------|------|----------------|
| Schemas | `app/schemas/common.py` | PyObjectId, PaginationParams, PaginatedResponse[T] |
| Schemas | `app/schemas/product.py` | ProductCreate, ProductUpdate, ProductResponse, ProductListItem |
| Repository | `app/repositories/product_repository.py` | All MongoDB operations for the products collection |
| Service | `app/services/product_service.py` | Business rules, final_price computation, filter/sort logic |
| Router | `app/api/routes/products.py` | HTTP handler — parses request, calls service, returns response |
| App | `app/main.py` | Registered `/products` router |

**Endpoints added:**
```
POST   /products/            Create product
GET    /products/            Paginated list with filters
GET    /products/{id}        Get single product
PUT    /products/{id}        Partial update
DELETE /products/{id}        Delete product
```

**Tests:** 41 integration + 40 unit = **81 new tests** (total 139, all passing)

---

### The Four-Layer Architecture in Practice

```
HTTP Request
    │
    ▼
Router (app/api/routes/products.py)
    │  Parses HTTP request body, query params
    │  Returns HTTP status codes
    │  NO business logic
    ▼
Service (app/services/product_service.py)
    │  Applies business rules (final_price, partial update logic)
    │  Converts raw dicts to Pydantic response schemas
    │  Orchestrates one or more repository calls
    │  NO database driver code
    ▼
Repository (app/repositories/product_repository.py)
    │  All MongoDB queries live here
    │  Wraps driver exceptions in domain exceptions
    │  Returns raw Python dicts (not Pydantic models)
    │  NO business logic
    ▼
MongoDB
    (products collection)
```

**Why this strict separation?**
- You can swap MongoDB for PostgreSQL by rewriting only the repository.
- You can add a Redis cache layer between the service and repository without touching the router.
- Business rules (should this product be created?) are tested independently of HTTP (does the response have the right status code?).
- The router is so thin that it rarely needs its own tests — the integration tests catch everything.

---

### How POST /products Works End-to-End

**Request:**
```http
POST /products/
Content-Type: application/json

{
  "sku": "SHIRT-001",
  "name": "Classic White Shirt",
  "brand": "Arrow",
  "category": "Men",
  "price": 999.0,
  "discount_percentage": 10.0,
  "stock_quantity": 50
}
```

**Step by step:**

1. **FastAPI receives the request** and matches it to `create_product(body, service)`.
2. **Pydantic validates `body`** as `ProductCreate`:
   - `sku` is stripped and uppercased by `@field_validator`.
   - `price` is checked to be >= 0.
   - `discount_percentage` is checked to be 0–90.
   - If any field fails, FastAPI returns 422 before the function runs.
3. **FastAPI resolves dependencies**: `get_database() → get_product_repository(db) → get_product_service(repo)`.
4. **`router.create_product`** calls `service.create_product(body)`.
5. **`service.create_product`**:
   - Computes `final_price = 999 * (1 - 10/100) = 899.1`.
   - Builds the MongoDB document dict (including `created_at`, `updated_at`).
   - Calls `repo.insert_one(document)`.
6. **`repo.insert_one`**:
   - Calls `await collection.insert_one(document)`.
   - If MongoDB raises `DuplicateKeyError` (SKU already exists), converts it to `DuplicateSKUException`.
   - Returns the document with `_id` populated.
7. **Service** calls `ProductResponse.model_validate(doc)` to convert the dict.
8. **Router** returns the `ProductResponse` — FastAPI serializes it to JSON with `by_alias=True`.
9. **HTTP 201 Created** with the product JSON.

---

### The `final_price` Business Rule

**Why store `final_price` in MongoDB?**

We could compute it on every read: `final_price = price * (1 - discount / 100)`. But:
- List queries often filter by price (`min_price`, `max_price`). Filtering on a computed field requires a `$expr` query or an aggregation pipeline, both much slower than an indexed field equality check.
- Sorting by `final_price` is not possible without either an index or an aggregation.

By storing `final_price` alongside `price` and `discount_percentage`, we can:
```
db.products.find({ final_price: { $gte: 500 } }).sort({ final_price: 1 })
```
This query uses indexes efficiently.

**The trade-off:** We must ensure `final_price` stays in sync. It is updated whenever `price` or `discount_percentage` changes:

```python
# In ProductService.update_product():
if "price" in update_fields or "discount_percentage" in update_fields:
    # Fetch the current value of whichever field wasn't in the update
    current = await self._repo.find_by_id(product_id)
    update_fields.setdefault("price", current["price"])
    update_fields.setdefault("discount_percentage", current["discount_percentage"])
    update_fields["final_price"] = self._compute_final_price(...)
```

This is a deliberate denormalization — trading storage space for query performance. The service layer is responsible for maintaining this invariant.

---

### How `model_dump(exclude_none=True)` Powers Partial Updates

**The problem:** A PUT /products/{id} request that only changes the name shouldn't overwrite all other fields with None.

**The solution:** `ProductUpdate` has all fields as `Optional[...]`. When the client sends:
```json
{"name": "New Name"}
```

Pydantic parses it as:
```python
ProductUpdate(name="New Name", price=None, brand=None, ...)
```

`data.model_dump(exclude_none=True)` returns only:
```python
{"name": "New Name"}
```

The repository then uses `$set`:
```python
await collection.find_one_and_update(
    {"_id": oid},
    {"$set": {"name": "New Name", "updated_at": now}},
    return_document=True
)
```

MongoDB's `$set` updates only the specified fields, leaving all others unchanged. This is true partial update semantics without needing the entire document to be resent.

---

### Why the Repository Wraps All PyMongo Exceptions

```python
try:
    result = await self._collection.insert_one(document)
except DuplicateKeyError:
    raise DuplicateSKUException(...)
except PyMongoError as exc:
    raise DatabaseException("Failed to create product.") from exc
```

**Why not let PyMongo exceptions bubble up?**

1. **Abstraction**: The service layer should not know or care about MongoDB-specific error types. If you switch to a different database driver, only the repository needs to change.
2. **Consistent error format**: The global exception handler in `main.py` converts `AppException` subclasses to a standard JSON error format. PyMongo exceptions would leak as unhandled 500 errors with confusing messages.
3. **Error messages**: `PyMongoError` messages are often driver-level jargon. `DatabaseException("Failed to create product.")` is a human-readable error.

---

### Why `find_one_and_update` Returns the Updated Document

The repository uses:
```python
find_one_and_update(
    {"_id": oid},
    {"$set": fields},
    return_document=True   # ← returns AFTER the update
)
```

Without `return_document=True`, MongoDB returns the document state **before** the update. We want the updated state to return to the client, so we must use `return_document=True`.

**The alternative:** Update, then find. But that's two round trips to MongoDB. `find_one_and_update` is a single atomic operation — the database engine applies the update and returns the result in one step. This eliminates the race condition where another request could modify the document between our update and our find.

---

### The PyObjectId Serialization Problem

MongoDB stores `_id` as a `bson.ObjectId` type (a 12-byte binary identifier, displayed as a 24-character hex string). Python's JSON encoder doesn't know how to serialize `ObjectId`.

**Our solution:** `PyObjectId(str)` — a subclass of `str` that validates the 24-char hex format.

In the Pydantic model:
```python
class ProductResponse(BaseModel):
    id: PyObjectId = Field(alias="_id")
    # ↑ Python field name: "id"   ↑ MongoDB document key: "_id"
```

- Pydantic reads `doc["_id"]` (an `ObjectId`) via the alias.
- `PyObjectId.validate()` converts it to a plain string.
- When FastAPI serializes the response with `model_dump(by_alias=True)`, it uses `"_id"` as the JSON key.

**Important realization from the bugs section:** FastAPI always serializes response models with `by_alias=True`. So the JSON response has `"_id"`, not `"id"`. Tests must look for `data["_id"]`.

---

### Pagination: Two Queries vs. $facet

The list endpoint runs two MongoDB queries:
```python
total = await collection.count_documents(filters)     # query 1
docs = await collection.find(filters).skip(n).limit(n)  # query 2
```

**Alternative:** MongoDB's `$facet` aggregation stage can return data and count in one pipeline:
```javascript
db.products.aggregate([
    { $match: filters },
    { $facet: {
        data: [{ $skip: n }, { $limit: n }],
        total: [{ $count: "count" }]
    }}
])
```

**Why we didn't use `$facet`:**
- `count_documents()` on an indexed field (like `status`) is a fast O(1) index scan. It doesn't scan documents.
- `$facet` always processes the entire matched result set before splitting — which is slower for large collections.
- Two queries are easier to read and debug than a complex aggregation pipeline.
- `$facet` shines when you need multiple computed metadata values (e.g., total + per-category counts + price histogram) in one query. For a simple count, the two-query approach wins.

---

### The Sort Field Whitelist

```python
_ALLOWED_SORT_FIELDS = {"price", "name", "created_at", "brand", "discount_percentage"}

sort_field = sort_by if sort_by in _ALLOWED_SORT_FIELDS else _DEFAULT_SORT_FIELD
```

**Why not let the client sort by any field?**
1. **Security**: Sorting by an un-indexed field forces MongoDB to load the entire collection into memory to sort it — a potential denial-of-service vector.
2. **Predictability**: If a client sends `sort_by=__proto__` or some internal field, the query still works but the result is undefined and potentially leaks internal data shape.
3. **All allowed fields have indexes** (defined in `indexes.py`), so sorts are O(log n) index scans.

---

### The `autouse=True` Fixture Pattern

```python
@pytest_asyncio.fixture(autouse=True)
async def clean_products(db: AsyncDatabase) -> None:
    await db["products"].delete_many({})   # setup: clean before test
    yield
    await db["products"].delete_many({})   # teardown: clean after test
```

**Why `autouse=True`?**
Without it, every integration test that creates products needs to manually clean up:
```python
async def test_something(client, db):
    ...
    await db["products"].delete_many({})  # repeated in every test
```

With `autouse=True`, the fixture runs automatically for every test in the module. This guarantees:
- Tests are independent regardless of execution order.
- A test that crashes before its cleanup code still gets cleaned up by the `autouse` fixture's teardown block.
- The test code itself is cleaner and focused on what it's testing.

**The double cleanup pattern** (before AND after):
- Before (`await db.delete_many({})` before `yield`): ensures a clean state even if a previous test left dirty data.
- After (`await db.delete_many({})` after `yield`): cleans up after the test so other test modules aren't affected.

---

### Bugs Found and Fixed in Stage 2

| Bug | Root Cause | Fix |
|-----|-----------|-----|
| `KeyError: 'id'` in tests | FastAPI serializes response with `by_alias=True`, so JSON key is `_id` not `id` | Changed test assertions from `data["id"]` to `data["_id"]` |
| `duplicate_sku` on second test | Tests shared MongoDB state; no cleanup between tests | Added `autouse=True` cleanup fixture |
| `NameError: pytest_asyncio not defined` | Missing import for module-level fixture | Added `import pytest_asyncio` |

---

### Interview Questions for Stage 2

1. **What is the repository pattern and why use it?**
   The repository pattern creates an abstraction layer between the application and the data source. All database queries for a given entity are in one class. Benefits: swap databases without changing business logic, test service layer by injecting a fake repository, all query logic in one place for easy review.

2. **What does `$set` do in MongoDB?**
   `$set` updates only the specified fields in a document, leaving all other fields unchanged. Without it, `update_one` would replace the entire document with the new document (a full replace), losing all fields not included in the update.

3. **Why is `final_price` stored in MongoDB instead of computed on read?**
   To enable efficient filtering and sorting. MongoDB can only filter and sort on stored fields using indexes. A computed field would require `$expr` queries or aggregation pipelines, which are much slower on large collections.

4. **How does Pydantic's `Field(alias="_id")` work?**
   The `alias` parameter tells Pydantic to read from a different key in the input data. `id: PyObjectId = Field(alias="_id")` means: when reading a MongoDB document, find the value at key `"_id"` and assign it to the Python attribute `id`. When serializing with `by_alias=True`, the JSON key will be `"_id"`.

5. **What is `model_dump(exclude_none=True)` and when do you use it?**
   `model_dump(exclude_none=True)` returns a dict of only the fields that are not `None`. Used for partial updates: clients send only the fields they want to change; `exclude_none=True` filters out the unset fields so the `$set` update only touches what was actually sent.

6. **How does FastAPI's dependency injection chain work for the product router?**
   ```
   Depends(get_database)       → returns AsyncDatabase
        ↓
   Depends(get_product_repository(db)) → returns ProductRepository
        ↓
   Depends(get_product_service(repo))  → returns ProductService
   ```
   FastAPI resolves this chain automatically, calling each function and caching the result for the duration of the request. In tests, `get_database` is overridden via `dependency_overrides`, which causes all downstream dependencies to also receive the test database.

7. **What is the difference between `return_document=True` and `return_document=False` in `find_one_and_update`?**
   `return_document=False` (default) returns the document **before** the update was applied. `return_document=True` returns the document **after** the update. For a PUT endpoint that returns the updated resource, you must use `return_document=True`. Using the default would return stale data.

8. **Why does the repository convert string IDs to `bson.ObjectId`?**
   MongoDB stores `_id` as a `bson.ObjectId` type internally. If you query with a plain string like `{"_id": "abc123"}`, MongoDB will find nothing because the type doesn't match. The conversion `ObjectId(product_id_string)` ensures the query matches the actual stored type.

9. **Why does an `autouse=True` fixture run twice (before and after yield)?**
   An async pytest fixture with `yield` is a context manager. The code before `yield` is setup (runs before the test), the code after `yield` is teardown (runs after the test, even if the test fails). `autouse=True` makes it apply to every test in scope automatically.

10. **What does `DuplicateKeyError` mean in MongoDB and how do we handle it?**
    `DuplicateKeyError` is raised by the MongoDB driver when an `insert_one` or `update_one` operation would violate a unique index constraint (in our case, the `sku_unique` index). The repository catches it and raises `DuplicateSKUException`, which the global handler converts to HTTP 409 Conflict. This is preferable to checking "does this SKU exist?" before inserting, which would create a race condition.

---

### Things to Understand Before Stage 3

- [ ] Why `final_price` is stored and not computed
- [ ] How `$set` differs from a full document replace
- [ ] Why the repository catches PyMongoError and re-raises as domain exceptions
- [ ] How `model_dump(exclude_none=True)` enables partial updates
- [ ] Why `find_one_and_update` with `return_document=True` is atomic
- [ ] How `Field(alias="_id")` maps MongoDB documents to Pydantic models
- [ ] Why `by_alias=True` in FastAPI serialization matters for test assertions
- [ ] The autouse fixture pattern for test isolation
- [ ] The sort field whitelist security rationale
- [ ] Two-query pagination vs. `$facet` aggregation trade-offs

---

---

## Stage 3: Search — MongoDB Full-Text Index

### What Was Built

| File | Purpose |
|------|---------|
| `app/schemas/search.py` | `SearchResult` (adds `score` field to `ProductListItem`), `SearchResponse` |
| `app/repositories/product_repository.py` | Added `text_search()` method |
| `app/services/product_service.py` | Added `search_products()` method |
| `app/api/routes/search.py` | `GET /search?q=...` |

**Endpoint:** `GET /search?q=<query>&category=&min_price=&max_price=&page=&limit=`

### How MongoDB Text Search Works

A text index was created in Stage 0 (`indexes.py`):
```python
await products.create_index(
    [("name", TEXT), ("description", TEXT), ("brand", TEXT)],
    name="text_search",
    weights={"name": 10, "brand": 5, "description": 1},
)
```

**Weights** mean a product whose *name* contains the query word scores 10x higher than one where it only appears in the description. This is how search relevance tuning works in MongoDB.

**The `$text` query:**
```python
text_filter = {"$text": {"$search": query}}
```

MongoDB matches documents where any of the indexed fields contain the query terms (case-insensitive, handles stemming).

**The `$meta` textScore projection:**
```python
projection = {
    "score": {"$meta": "textScore"},
}
cursor.sort([("score", {"$meta": "textScore"})])
```

`$meta "textScore"` injects the computed relevance score into each result document and allows sorting by it. Higher score = better match.

### Why Search is a Separate Endpoint from /products

| Concern | `/products` (list) | `/search` |
|---------|--------------------|-----------|
| Use case | Browse catalog | Find specific items |
| Sort | Configurable (price, name, date) | Fixed: relevance score |
| Response | `ProductListItem` | `SearchResult` (+ score) |
| Query param | No text query | `q` required, min 2 chars |
| Filters | All | Category + price only |

Mixing them into one endpoint would produce a messy API with optional parameters that interact confusingly.

### Interview Questions — Stage 3

1. **What is a MongoDB text index?** A special index type that tokenizes and indexes string fields for full-text search. Supports case-insensitive matching, stop-word removal, and relevance scoring.

2. **What are index weights in MongoDB text search?** Weights control the relative relevance contribution of each indexed field. A match in a field with weight 10 scores 10x higher than a match in a field with weight 1, allowing name matches to rank higher than description matches.

3. **What does `{"$meta": "textScore"}` do?** In a projection, it adds a `score` field to each result document containing the computed text relevance score. In a sort, it orders results by that score (descending = best match first).

4. **What is the minimum query length and why?** 2 characters, enforced by `Query(min_length=2)` in FastAPI. An empty `$text` query raises a MongoDB error; very short queries (1 char) are stop words in most languages and return no useful results.

5. **What are the limitations of MongoDB text search vs. Elasticsearch?** MongoDB text search lacks: phrase matching, fuzzy matching (typos), field boosting at query time, synonyms, faceted counts, and advanced tokenization. Elasticsearch (or Atlas Search) is preferred for production-grade search.

---

## Stage 4: Inventory Management

### What Was Built

| File | Purpose |
|------|---------|
| `app/schemas/inventory.py` | `InventoryResponse`, `InventoryUpdate` (delta), `LowStockItem` |
| `app/repositories/inventory_repository.py` | `get_or_create`, `adjust_stock` (atomic `$inc`), `find_low_stock` |
| `app/services/inventory_service.py` | Validates product exists, delegates to repo |
| `app/api/routes/inventory.py` | 3 endpoints |

**Endpoints:**
```
GET  /inventory/{product_id}          → stock level (creates with qty=0 if new)
POST /inventory/{product_id}/adjust   → adjust stock (+ or -)
GET  /inventory/low-stock?threshold=  → items below threshold
```

### The Atomic `$inc` Stock Deduction Pattern

This is the most important concept in inventory management:

**BAD — read-modify-write (race condition):**
```python
inv = await collection.find_one({"product_id": id})
new_qty = inv["quantity"] - requested
await collection.update_one({"product_id": id}, {"$set": {"quantity": new_qty}})
```
If two requests run simultaneously, both read `quantity=10`, both compute `new_qty=8`, and both write `8` — you've lost one deduction.

**GOOD — atomic `$inc` with guard filter:**
```python
updated = await collection.find_one_and_update(
    {"product_id": id, "quantity": {"$gte": requested}},  # guard
    {"$inc": {"quantity": -requested}},                   # atomic
    return_document=True,
)
if updated is None:
    raise InsufficientStockException(...)
```
MongoDB processes this as a single atomic operation at the server. The filter `quantity >= requested` ensures the deduction only happens if sufficient stock exists. If two requests race: one will succeed and one will find `quantity < requested` and fail cleanly.

### Lazy Inventory Initialization (`get_or_create`)

```python
await collection.find_one_and_update(
    {"product_id": product_id},
    {"$setOnInsert": {"quantity": 0, ...}},
    upsert=True,
    return_document=True,
)
```

`$setOnInsert` only applies fields if this is a new insert (not a find). This creates the inventory record atomically the first time it's accessed — no separate "create inventory" step needed when creating a product.

### Why Inventory is Separate from Products

- **Independent scale**: inventory changes constantly (every sale, every restock). Product catalog changes rarely.
- **Locking**: high-frequency inventory writes on the same document would create lock contention if inventory were embedded in the product document.
- **Separation of concerns**: catalog manages product metadata; inventory manages stock levels.
- **Future**: could be sharded by warehouse, or replaced with a dedicated stock management service.

### Interview Questions — Stage 4

1. **Why use `$inc` instead of `$set` for stock updates?** `$inc` is atomic — MongoDB applies the increment as a single operation without reading the current value. `$set` requires a read-modify-write cycle that creates a race condition under concurrent requests.

2. **What is `$setOnInsert`?** An update operator that only applies its fields when the operation results in an insert (upsert=True creates a new document). Used for lazy initialization: create a default record only if none exists.

3. **How do you prevent stock from going negative?** Add a filter condition `{"quantity": {"$gte": abs(delta)}}` to the update. If the condition doesn't match, `find_one_and_update` returns `None` without modifying the document, which we interpret as insufficient stock.

4. **What is the difference between `upsert=True` and a separate insert?** Upsert is atomic — find-or-insert happens in one server operation. Separate insert-if-not-found creates a race where two concurrent requests could both find "not found" and both try to insert, causing a duplicate key error. Upsert handles this automatically.

---

## Stage 5: Shopping Cart

### What Was Built

| File | Purpose |
|------|---------|
| `app/schemas/cart.py` | `CartItem`, `CartItemAdd`, `CartItemUpdate`, `CartResponse` |
| `app/repositories/cart_repository.py` | CRUD for cart items + total recomputation |
| `app/services/cart_service.py` | Product validation, price snapshot |
| `app/api/routes/cart.py` | 5 endpoints using `X-User-ID` header |

**Endpoints:**
```
GET    /cart                         → get/create cart
POST   /cart/items                   → add item (or replace)
PUT    /cart/items/{product_id}      → update quantity
DELETE /cart/items/{product_id}      → remove item
DELETE /cart                         → clear cart
```

### Price Snapshot — The Most Important Cart Design Decision

When a user adds a product to the cart, we record the price *at that moment*:
```python
unit_price = product.get("final_price", product["price"])
item_doc = {
    "unit_price": unit_price,
    "subtotal": round(unit_price * data.quantity, 2),
    ...
}
```

If the product price changes after the item is added, the cart still shows the original price. This is **intentional and standard** e-commerce behaviour:
- The user saw a price and decided to buy at that price.
- Changing the cart price without warning would be a UX betrayal.
- Most retailers honor the cart price for a session window (e.g. 24 hours).

The snapshot is a **denormalization** — we store data that's also in the products collection. This is a deliberate trade-off: data duplication in exchange for price stability.

### The `$pull` + `$push` Item Upsert Pattern

MongoDB doesn't have a native "upsert array element" operation. To replace an existing item with a new one (e.g. update quantity), we:
```python
# 1. Remove existing item (if any)
await collection.update_one({"user_id": user_id},
    {"$pull": {"items": {"product_id": item["product_id"]}}})

# 2. Push new item
await collection.update_one({"user_id": user_id},
    {"$push": {"items": item}})
```

This is two operations (not atomic). The simpler alternative uses the positional operator `$` but requires knowing the array index in advance, which means an extra find first.

For a learning project with low concurrency, `$pull` + `$push` is clear and correct. In production with high concurrency, you'd use MongoDB transactions.

### User Identity via HTTP Header (Pre-Auth Pattern)

```python
def _user_id(x_user_id: str = Header(...)) -> str:
    return x_user_id.strip()
```

Using a FastAPI `Header` dependency means the user_id injection point is a single function. When Stage 7 (auth) is built, this function is the only place that changes — all route handlers that use `Depends(_user_id)` automatically get JWT-based identity with zero route changes.

This is called the **Dependency Inversion Principle** applied to authentication: routes depend on an abstract identity interface, not on a concrete "read from header" implementation.

### Interview Questions — Stage 5

1. **Why snapshot the price instead of reading it from the product on every request?** Price stability — the customer saw a specific price and shouldn't have it change in their cart. Also, if a product is deleted, the cart would lose the price reference.

2. **What is the `$pull` operator?** Removes matching elements from an array field. `$pull: {"items": {"product_id": "abc"}}` removes all items from the `items` array where `product_id == "abc"`.

3. **What is the `$push` operator?** Appends an element to an array field. Used with `$addToSet` for unique-set semantics; plain `$push` allows duplicates.

4. **How do you use the positional operator `$` in MongoDB?** In `items.$.quantity`, the `$` refers to the first array element that matched the query filter. For example: `update_one({"items.product_id": "abc"}, {"$set": {"items.$.quantity": 5}})` updates the matching element's quantity.

5. **Why might you prefer MongoDB transactions for cart mutations over the $pull+$push approach?** Transactions guarantee atomicity across multiple operations. Without a transaction, if the server crashes between `$pull` and `$push`, the item is lost from the cart. For cart operations this is usually tolerable; for financial operations (orders), transactions are essential.

---

## Stage 6: Orders — The Full Checkout Flow

### What Was Built

| File | Purpose |
|------|---------|
| `app/schemas/order.py` | `OrderStatus` enum, `VALID_TRANSITIONS` state machine, order schemas |
| `app/repositories/order_repository.py` | Insert, status update, paginated user query |
| `app/services/order_service.py` | 5-step checkout, ownership enforcement, state machine |
| `app/api/routes/orders.py` | POST (201), GET list, GET single, PUT status |

**Endpoints:**
```
POST /orders/                  → place order from cart (201)
GET  /orders/                  → list user orders (paginated + status filter)
GET  /orders/{id}              → get single order (ownership enforced)
PUT  /orders/{id}/status       → advance status (state machine)
```

### The 5-Step Checkout Flow

```
place_order(user_id, shipping_address):
  1. Fetch cart → validate not empty
  2. Pre-flight stock check (read-only, all items)
  3. Deduct inventory for all items ($inc, atomic)
  4. Create order document (status=pending)
  5. Clear cart
```

**Why pre-flight check before deduction?**
If we deducted item-by-item and item 3 failed the stock check, items 1 and 2 would already be deducted without an order being created. The pre-flight check catches the failure BEFORE any mutations. It's not 100% safe (race condition between check and deduct), but it's the pragmatic approach without transactions.

**Production note — use MongoDB transactions:**
```python
async with await client.start_session() as session:
    async with session.start_transaction():
        # steps 3+4 together — atomic
        for item in items:
            await inv_repo.adjust_stock(item["product_id"], -item["quantity"], session=session)
        await order_repo.insert_one(order_doc, session=session)
    # session commits automatically; on error, transaction rolls back
```

### The Status State Machine

```
VALID_TRANSITIONS = {
    "pending":   ["confirmed", "cancelled"],
    "confirmed": ["shipped",   "cancelled"],
    "shipped":   ["delivered"],
    "delivered": [],      ← terminal state
    "cancelled": [],      ← terminal state
}
```

Storing the state machine as a dictionary makes the rules explicit, self-documenting, and testable without mocking. The service checks:
```python
allowed = VALID_TRANSITIONS.get(current_status, [])
if new_status not in allowed:
    raise InvalidStatusTransitionException(...)
```

Adding a new status (e.g. `"refunded"`) requires only updating `VALID_TRANSITIONS` — no if/elif chains to modify.

### Ownership Enforcement (Returning 404 vs 403)

```python
if doc["user_id"] != user_id:
    raise OrderNotFoundException(...)  # returns 404, not 403
```

Returning **404** instead of **403** when the order exists but belongs to another user prevents **information disclosure**: a 403 reveals that an order with that ID exists. 404 reveals nothing. This is a security best practice.

### Order List Projection

```python
projection = {
    "items": 0,           # omit items array
    "shipping_address": 0,
    "notes": 0,
}
```

The list endpoint excludes large fields to keep payloads small. Clients call `GET /orders/{id}` to get the full order with items. This is the same lightweight-list / full-detail pattern used in Stage 2 for products.

### Bugs Found and Fixed in Stage 6

| Bug | Fix |
|-----|-----|
| `NameError: OrderNotFoundException not defined` in service | Added missing import to `order_service.py` |

### Interview Questions — Stage 6

1. **What is a state machine and how did you implement it?** A state machine restricts which states an entity can move between. Implemented as a dictionary `{current_state: [allowed_next_states]}`. The service looks up the current state, checks if the requested transition is allowed, and raises an error if not.

2. **Why validate stock before deducting (pre-flight check)?** To give a clean error before any mutations occur. If item 3 of 5 fails, items 1 and 2 haven't been deducted yet, so no cleanup is needed.

3. **Why clear the cart AFTER creating the order (not before)?** If order creation fails (database error), the cart should remain intact so the user can retry. Cart clearing is the last step — it only happens on success.

4. **What is the difference between HTTP 403 and 404 for ownership violations?** 403 Forbidden reveals that the resource exists but you don't have access. 404 Not Found reveals nothing about whether the resource exists. For privacy and security, 404 is preferred when you don't want to confirm existence to unauthorized users.

5. **How would you make the checkout flow truly atomic?** Use MongoDB multi-document transactions with a session. Wrap steps 3+4 (inventory deduction + order creation) in `session.start_transaction()`. On any error, the transaction rolls back automatically — no partial state is left in the database.

6. **Why store items in the order document instead of referencing products?** The order is a historical record. Product prices, names, and details can change. The order must always show exactly what was purchased at exactly the price paid, regardless of future catalog changes. This is the same snapshot principle used in the cart.

---

## Summary: Test Coverage After Stages 3–6

| Stage | Unit Tests | Integration Tests | Total Added |
|-------|-----------|-------------------|-------------|
| 3 — Search | 0 | 13 | 13 |
| 4 — Inventory | 0 | 21 | 21 |
| 5 — Cart | 0 | 21 | 21 |
| 6 — Orders | 25 | 29 | 54 |
| **All stages** | **65 unit** | **181 integration** | **246 total** |

---

## Architecture Overview (Post Stage 6)

```
Client Request
     │
     ▼
FastAPI Router (HTTP boundary — thin handlers only)
     │  Parses/validates via Pydantic, injects dependencies
     ▼
Service Layer (business logic)
     │  Orchestrates multiple repository calls
     │  Enforces business rules and state machines
     ▼
Repository Layer (data access)
     │  Single MongoDB collection per repository
     │  Atomic operations ($inc, $set, find_one_and_update)
     │  Wraps PyMongoError in domain exceptions
     ▼
MongoDB (fashion_commerce / fashion_commerce_test)
     Collections: products, inventory, carts, orders
```

**Collections and their indexes:**

| Collection | Key Indexes |
|-----------|-------------|
| products | sku (unique), text (name+brand+description), category+price compound, status, final_price |
| inventory | product_id (unique), quantity |
| carts | user_id (unique) |
| orders | user_id+created_at compound, status |

---
