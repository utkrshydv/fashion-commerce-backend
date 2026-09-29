# Fashion Commerce Platform Backend

A production-style RESTful backend for a fashion e-commerce platform, built as a portfolio project demonstrating clean Python backend architecture.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Framework | FastAPI 0.115+ |
| Validation | Pydantic v2 |
| Database | MongoDB 7 |
| DB Driver | PyMongo Async (native async, no Motor) |
| Config | Pydantic Settings |
| Testing | pytest + pytest-asyncio + httpx |
| Runtime | Python 3.12 |
| Containers | Docker + Docker Compose |

## Architecture

```
Request
  â””â”€â–º Router (app/api/routes/)       â† thin HTTP layer, no business logic
        â””â”€â–º Service (app/services/)  â† business logic, orchestration
              â””â”€â–º Repository (app/repositories/)  â† database queries only
                    â””â”€â–º MongoDB
```

Configuration, exceptions, logging, and database lifecycle live in `app/core/` and `app/db/`.

## Quick Start

### Local (without Docker)

```bash
# 1. Create virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env â€” set MONGODB_URI if MongoDB is not running locally

# 4. Run the API
uvicorn app.main:app --reload
```

API docs available at: http://localhost:8000/docs

### Docker Compose

```bash
docker compose up --build
```

This starts MongoDB (with persistent storage) and the API.  
API: http://localhost:8000  
Docs: http://localhost:8000/docs

### Running Tests

```bash
pytest
```

## API Endpoints (planned)

| Method | Path | Description |
|--------|------|-------------|
| GET | /health | Health check |
| POST | /products | Create product |
| GET | /products | List products (filter, paginate, sort) |
| GET | /products/{id} | Get product |
| PUT | /products/{id} | Update product |
| DELETE | /products/{id} | Delete product |
| GET | /search/products | Full-text search |
| GET | /cart/{user_id} | Get cart |
| POST | /cart/{user_id}/items | Add item |
| PATCH | /cart/{user_id}/items/{product_id} | Update quantity |
| DELETE | /cart/{user_id}/items/{product_id} | Remove item |
| DELETE | /cart/{user_id} | Clear cart |
| POST | /orders/{user_id} | Create order from cart |
| GET | /orders/{user_id} | List orders |
| GET | /orders/{user_id}/{order_id} | Get order |
| PATCH | /orders/{user_id}/{order_id}/status | Update order status |
| GET | /inventory/{product_id} | Get inventory |
| PATCH | /inventory/{product_id}/increase | Increase stock |
| PATCH | /inventory/{product_id}/decrease | Decrease stock |

## Project Structure

```
app/
â”œâ”€â”€ main.py                     # App factory + lifespan handler
â”œâ”€â”€ api/routes/                 # HTTP route handlers (thin)
â”œâ”€â”€ core/                       # Config, exceptions, logging
â”œâ”€â”€ db/                         # MongoDB client + indexes
â”œâ”€â”€ models/                     # Document shapes (DB layer)
â”œâ”€â”€ schemas/                    # Request/Response schemas (API layer)
â”œâ”€â”€ repositories/               # MongoDB queries
â”œâ”€â”€ services/                   # Business logic
â””â”€â”€ utils/

tests/
â”œâ”€â”€ unit/                       # Service/logic unit tests
â””â”€â”€ integration/                # Full request-to-DB tests

scripts/
â””â”€â”€ seed_database.py            # Development seed data
```

## Build Stages

| Stage | Description | Status |
|-------|-------------|--------|
| 0 | Architecture & scaffolding | Complete |
| 1 | FastAPI foundation + DB connection + health | Complete |
| 2 | Product catalog CRUD | Complete |
| 3 | Search + filtering + indexes | Complete |
| 4 | Inventory management | Complete |
| 5 | Shopping cart | Complete |
| 6 | Orders | Complete |
| 7 | Background processing (APScheduler / Celery) | Complete |
| 8 | Hardened test suite (coverage, edge cases) | Complete |
| 9 | Docker + seed data | Pending |
| 10 | End-to-end verification + README polish | Pending |

## Learning Document

See [learning.md](learning.md) for a detailed explanation of every architectural decision, concept, and interview question per stage.
