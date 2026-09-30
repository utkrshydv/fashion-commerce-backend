# Fashion Commerce Platform Backend

A production-style RESTful backend for a fashion e-commerce platform.
Built as a portfolio project demonstrating clean Python backend architecture,
async MongoDB integration, background processing, and a comprehensive test suite.

296 tests | 89% coverage | 13 endpoints | 4 collections | 2 background jobs

---

## Tech Stack

| Layer          | Technology                                  |
|----------------|---------------------------------------------|
| Framework      | FastAPI 0.115+                              |
| Validation     | Pydantic v2                                 |
| Database       | MongoDB 7                                   |
| DB Driver      | PyMongo Async (native async, no Motor)      |
| Config         | Pydantic Settings                           |
| Scheduler      | APScheduler 3.x (AsyncIOScheduler)          |
| Testing        | pytest + pytest-asyncio + httpx             |
| Coverage       | pytest-cov (branch coverage, 89%)           |
| Runtime        | Python 3.12                                 |
| Containers     | Docker (multi-stage) + Docker Compose       |

---

## Architecture

```
HTTP Request
    |
    v
Router  (app/api/routes/)       <- thin: parse, validate, return
    |
    v
Service (app/services/)         <- business logic, orchestration
    |
    v
Repository (app/repositories/)  <- MongoDB queries only
    |
    v
MongoDB (4 collections)
```

Each layer has a single responsibility. Business logic never touches HTTP.
Database queries never contain validation rules.

**Supporting modules:**
- `app/core/` - Config, exceptions, logging, scheduler
- `app/db/`   - Connection lifecycle, index management
- `app/utils/jobs.py` - Background job functions (pure async, testable)

---

## Quick Start

### Option A: Local (MongoDB must be running)

```bash
# 1. Clone and enter the project
git clone https://github.com/utkrshydv/fashion-commerce-backend.git
cd fashion-commerce-backend

# 2. Create virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux / macOS

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
copy .env.example .env        # Windows
# cp .env.example .env        # Linux / macOS
# Edit .env if MongoDB is not on localhost:27017

# 5. Start the API
uvicorn app.main:app --reload
```

API:        http://localhost:8000
Swagger UI: http://localhost:8000/docs
ReDoc:      http://localhost:8000/redoc

### Option B: Docker Compose (recommended, no local MongoDB needed)

```bash
# Build and start both services (MongoDB + API)
docker compose up --build

# OR run in background
docker compose up --build -d

# View logs
docker compose logs -f api

# Stop everything
docker compose down

# Stop + delete all data volumes
docker compose down -v
```

API:        http://localhost:8000
Swagger UI: http://localhost:8000/docs

### Seed the database with sample data

After the API is running (local or Docker):

```bash
# Local
python scripts/seed_database.py

# Docker
docker compose exec api python scripts/seed_database.py
```

Seeds: 26 products, inventory records, 6 orders across 3 users.

---

## API Endpoints

| Method | Path                        | Description                          | Auth Header     |
|--------|-----------------------------|--------------------------------------|-----------------|
| GET    | /health                     | Service health + DB connectivity     | None            |
| POST   | /products/                  | Create a product                     | None            |
| GET    | /products/                  | List products (filter, paginate)     | None            |
| GET    | /products/{id}              | Get product by ID                    | None            |
| PUT    | /products/{id}              | Update product                       | None            |
| DELETE | /products/{id}              | Delete product                       | None            |
| GET    | /search/                    | Full-text search (relevance ranked)  | None            |
| GET    | /inventory/{product_id}     | Get stock level                      | None            |
| POST   | /inventory/{product_id}/adjust | Adjust stock (+/-)               | None            |
| GET    | /inventory/low-stock        | Products below stock threshold       | None            |
| GET    | /cart/                      | Get or create user cart              | X-User-ID       |
| POST   | /cart/items                 | Add item to cart                     | X-User-ID       |
| PUT    | /cart/items/{product_id}    | Update item quantity                 | X-User-ID       |
| DELETE | /cart/items/{product_id}    | Remove item from cart                | X-User-ID       |
| DELETE | /cart/                      | Clear cart                           | X-User-ID       |
| POST   | /orders/                    | Place order from cart                | X-User-ID       |
| GET    | /orders/                    | List user orders (paginated)         | X-User-ID       |
| GET    | /orders/{id}                | Get single order (ownership checked) | X-User-ID       |
| PUT    | /orders/{id}/status         | Advance order status (state machine) | X-User-ID       |

User identity is passed via `X-User-ID: <any-string>` header (pre-auth pattern).

---

## Running Tests

```bash
# Run all 296 tests
pytest

# Run with coverage report
pytest --cov=app --cov-report=term-missing

# Run only unit tests
pytest tests/unit/

# Run only integration tests
pytest tests/integration/

# Run a specific file
pytest tests/integration/test_orders.py -v

# Run a specific test
pytest tests/integration/test_orders.py::TestPlaceOrder::test_empty_cart_returns_400 -v
```

Tests use a separate `fashion_commerce_test` database. No production data is affected.

---

## Background Jobs

Two jobs run automatically when the API starts:

| Job                    | Schedule    | What it does                                    |
|------------------------|-------------|--------------------------------------------------|
| `low_stock_alert`      | Every 60min | Logs products with stock <= 10                  |
| `auto_cancel_orders`   | Every 30min | Cancels pending orders older than 24 hours      |

Jobs are implemented as pure async functions in `app/utils/jobs.py` and are
tested independently without starting the scheduler.

---

## Project Structure

```
fashion-commerce-backend/
|
+-- app/
|   +-- main.py                     # App factory, lifespan, global exception handler
|   +-- api/
|   |   +-- routes/
|   |       +-- health.py           # GET /health
|   |       +-- products.py         # CRUD /products
|   |       +-- search.py           # GET /search
|   |       +-- inventory.py        # /inventory
|   |       +-- cart.py             # /cart
|   |       +-- orders.py           # /orders
|   +-- services/                   # Business logic layer
|   +-- repositories/               # MongoDB data access layer
|   +-- schemas/                    # Pydantic request/response models
|   +-- db/
|   |   +-- client.py               # AsyncMongoClient lifecycle
|   |   +-- indexes.py              # Index definitions (idempotent)
|   +-- core/
|   |   +-- config.py               # Pydantic Settings
|   |   +-- exceptions.py           # Custom exception hierarchy
|   |   +-- logging.py              # Structured logging
|   |   +-- scheduler.py            # APScheduler setup
|   +-- utils/
|       +-- jobs.py                 # Background job functions
|
+-- tests/
|   +-- conftest.py                 # Shared fixtures (db, client)
|   +-- unit/                       # 87 unit tests (no I/O)
|   +-- integration/                # 209 integration tests (real MongoDB)
|
+-- scripts/
|   +-- seed_database.py            # Development seed data
|
+-- Dockerfile                      # Multi-stage build
+-- docker-compose.yml              # MongoDB + API services
+-- .env.example                    # Environment variable template
+-- requirements.txt
+-- pyproject.toml                  # pytest + coverage config
+-- learning.md                     # Architecture decisions + interview prep
```

---

## Build Stages

| Stage | Description                               | Status   |
|-------|-------------------------------------------|----------|
| 0     | Architecture and scaffolding              | Complete |
| 1     | FastAPI foundation, DB connection, health | Complete |
| 2     | Product catalog CRUD                      | Complete |
| 3     | Search with MongoDB full-text index       | Complete |
| 4     | Inventory management (atomic updates)     | Complete |
| 5     | Shopping cart (price snapshot pattern)    | Complete |
| 6     | Orders (checkout flow, state machine)     | Complete |
| 7     | Background processing (APScheduler)       | Complete |
| 8     | Hardened test suite, 89% coverage         | Complete |
| 9     | Docker multi-stage build, seed data       | Complete |
| 10    | End-to-end verification, README polish    | Complete |

---

## Learning Document

See [learning.md](learning.md) for detailed explanations of every architectural
decision, MongoDB pattern, and interview question for each stage.

Topics covered: layered architecture, Pydantic v2, MongoDB async driver,
atomic stock updates, price snapshotting, state machines, APScheduler,
multi-stage Docker, branch coverage, and more.
