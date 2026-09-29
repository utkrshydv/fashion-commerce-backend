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
