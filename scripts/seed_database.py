#!/usr/bin/env python3
"""
scripts/seed_database.py

Populates the development database with realistic fashion e-commerce data.

Usage:
    # Local (with .venv active):
    python scripts/seed_database.py

    # Inside Docker (after docker compose up):
    docker compose exec api python scripts/seed_database.py

    # Against a specific database:
    MONGODB_DATABASE=fashion_commerce_staging python scripts/seed_database.py

What gets seeded:
    - 30 products across Men / Women / Kids / Accessories categories
    - Inventory records for every product (realistic stock levels)
    - 3 sample users, each with 2 orders in various status stages
    - Carts are intentionally left empty (users should add their own)

Idempotency:
    Running this script twice is safe. Products are matched by SKU and
    upserted, so no duplicates are created.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any

# Allow running as a top-level script without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))

from pymongo import AsyncMongoClient, TEXT, ASCENDING, DESCENDING
from pymongo.asynchronous.database import AsyncDatabase
from bson import ObjectId

# ── Configuration ─────────────────────────────────────────────────────────────

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "fashion_commerce")

# ── Seed Data ─────────────────────────────────────────────────────────────────

NOW = datetime.now(timezone.utc)


def _price(base: float, discount: float = 0.0) -> Dict[str, float]:
    final = round(base * (1 - discount / 100), 2)
    return {"price": base, "discount_percentage": discount, "final_price": final}


PRODUCTS: List[Dict[str, Any]] = [
    # ── Men ───────────────────────────────────────────────────────────────────
    {
        "sku": "MEN-SHIRT-001",
        "name": "Classic Oxford Button-Down Shirt",
        "brand": "ArrowFit",
        "category": "Men",
        "description": "A timeless Oxford shirt crafted from 100% premium cotton. Perfect for office or casual wear.",
        **_price(1299.0, 10),
        "stock_quantity": 80,
        "available_sizes": ["S", "M", "L", "XL", "XXL"],
        "available_colors": ["White", "Blue", "Grey"],
        "image_urls": ["https://images.unsplash.com/photo-1602810318383-e386cc2a3ccf?w=400"],
        "status": "active",
    },
    {
        "sku": "MEN-JEANS-001",
        "name": "Slim Fit Stretch Denim Jeans",
        "brand": "DenimCo",
        "category": "Men",
        "description": "Modern slim-fit jeans with 2% elastane for all-day comfort. Fade-resistant dark wash.",
        **_price(2499.0, 20),
        "stock_quantity": 60,
        "available_sizes": ["28", "30", "32", "34", "36"],
        "available_colors": ["Dark Blue", "Black", "Grey"],
        "image_urls": ["https://images.unsplash.com/photo-1542272454315-4c01d7abdf4a?w=400"],
        "status": "active",
    },
    {
        "sku": "MEN-TSHIRT-001",
        "name": "Premium Pima Cotton T-Shirt",
        "brand": "BasicLux",
        "category": "Men",
        "description": "Ultra-soft Pima cotton tee with a relaxed fit. The only basic you'll ever need.",
        **_price(799.0, 0),
        "stock_quantity": 150,
        "available_sizes": ["XS", "S", "M", "L", "XL"],
        "available_colors": ["White", "Black", "Navy", "Olive"],
        "image_urls": ["https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?w=400"],
        "status": "active",
    },
    {
        "sku": "MEN-CHINO-001",
        "name": "Stretch Chino Trousers",
        "brand": "SlimLine",
        "category": "Men",
        "description": "Smart casual chinos with stretch fabric. Wrinkle-resistant finish.",
        **_price(1899.0, 15),
        "stock_quantity": 45,
        "available_sizes": ["28", "30", "32", "34"],
        "available_colors": ["Khaki", "Navy", "Olive"],
        "image_urls": ["https://images.unsplash.com/photo-1624378439575-d8705ad7ae80?w=400"],
        "status": "active",
    },
    {
        "sku": "MEN-JACKET-001",
        "name": "Quilted Puffer Jacket",
        "brand": "WinterEdge",
        "category": "Men",
        "description": "Lightweight quilted jacket with down-alternative fill. Water-resistant shell.",
        **_price(3999.0, 25),
        "stock_quantity": 30,
        "available_sizes": ["S", "M", "L", "XL"],
        "available_colors": ["Black", "Navy", "Olive"],
        "image_urls": ["https://images.unsplash.com/photo-1551698618-1dfe5d97d256?w=400"],
        "status": "active",
    },
    {
        "sku": "MEN-POLO-001",
        "name": "Pique Cotton Polo Shirt",
        "brand": "ClassicCo",
        "category": "Men",
        "description": "Breathable pique polo with ribbed collar and cuffs. Semi-formal versatility.",
        **_price(1099.0, 0),
        "stock_quantity": 7,   # ← low stock intentional
        "available_sizes": ["S", "M", "L", "XL"],
        "available_colors": ["White", "Navy", "Red"],
        "image_urls": ["https://images.unsplash.com/photo-1626497764746-6dc36546b388?w=400"],
        "status": "active",
    },
    {
        "sku": "MEN-SUIT-001",
        "name": "Two-Piece Wool Blend Suit",
        "brand": "FormalEdge",
        "category": "Men",
        "description": "Premium wool-blend suit with notch lapels. Single-breasted, two-button closure.",
        **_price(8999.0, 10),
        "stock_quantity": 15,
        "available_sizes": ["38", "40", "42", "44"],
        "available_colors": ["Charcoal", "Navy", "Black"],
        "image_urls": ["https://images.unsplash.com/photo-1507679799987-c73779587ccf?w=400"],
        "status": "active",
    },
    {
        "sku": "MEN-SHORT-001",
        "name": "Cargo Shorts",
        "brand": "OutdoorWear",
        "category": "Men",
        "description": "Multi-pocket cargo shorts with drawstring waist. Quick-dry fabric.",
        **_price(999.0, 0),
        "stock_quantity": 55,
        "available_sizes": ["S", "M", "L", "XL"],
        "available_colors": ["Khaki", "Black", "Olive"],
        "image_urls": ["https://images.unsplash.com/photo-1591195853828-11db59a44f43?w=400"],
        "status": "active",
    },

    # ── Women ─────────────────────────────────────────────────────────────────
    {
        "sku": "WOM-DRESS-001",
        "name": "Floral Wrap Midi Dress",
        "brand": "BloomWear",
        "category": "Women",
        "description": "A-line wrap dress in floral chiffon. Adjustable waist tie for a flattering fit.",
        **_price(2199.0, 15),
        "stock_quantity": 40,
        "available_sizes": ["XS", "S", "M", "L", "XL"],
        "available_colors": ["Floral Blue", "Floral Pink", "Floral Green"],
        "image_urls": ["https://images.unsplash.com/photo-1595777457583-95e059d581b8?w=400"],
        "status": "active",
    },
    {
        "sku": "WOM-TOP-001",
        "name": "Satin Cami Top",
        "brand": "SilkLine",
        "category": "Women",
        "description": "Luxurious satin cami with adjustable straps. Wear alone or layered.",
        **_price(899.0, 0),
        "stock_quantity": 65,
        "available_sizes": ["XS", "S", "M", "L"],
        "available_colors": ["Champagne", "Black", "Dusty Pink", "Sage"],
        "image_urls": ["https://images.unsplash.com/photo-1485231183945-fffde7b62f48?w=400"],
        "status": "active",
    },
    {
        "sku": "WOM-JEANS-001",
        "name": "High-Rise Skinny Jeans",
        "brand": "DenimCo",
        "category": "Women",
        "description": "High-waist skinny jeans that lift and sculpt. Four-way stretch denim.",
        **_price(1999.0, 20),
        "stock_quantity": 50,
        "available_sizes": ["24", "26", "28", "30", "32"],
        "available_colors": ["Dark Blue", "Black", "Light Blue"],
        "image_urls": ["https://images.unsplash.com/photo-1541099649105-f69ad21f3246?w=400"],
        "status": "active",
    },
    {
        "sku": "WOM-BLAZER-001",
        "name": "Structured Linen Blazer",
        "brand": "TailoredByYou",
        "category": "Women",
        "description": "Relaxed linen blazer with a structured silhouette. Single-button closure.",
        **_price(3299.0, 0),
        "stock_quantity": 25,
        "available_sizes": ["XS", "S", "M", "L", "XL"],
        "available_colors": ["Ivory", "Camel", "Black"],
        "image_urls": ["https://images.unsplash.com/photo-1591369822096-ffd140ec948f?w=400"],
        "status": "active",
    },
    {
        "sku": "WOM-SKIRT-001",
        "name": "Pleated Midi Skirt",
        "brand": "FlowWear",
        "category": "Women",
        "description": "Elegant pleated midi skirt in breathable georgette. Elasticated waistband.",
        **_price(1499.0, 10),
        "stock_quantity": 35,
        "available_sizes": ["XS", "S", "M", "L"],
        "available_colors": ["Blush", "Mauve", "Black", "Teal"],
        "image_urls": ["https://images.unsplash.com/photo-1583496661160-fb5886a0aaaa?w=400"],
        "status": "active",
    },
    {
        "sku": "WOM-KURTA-001",
        "name": "Embroidered Cotton Kurta",
        "brand": "EthnicLux",
        "category": "Women",
        "description": "Handcrafted embroidered kurta in pure cotton. Traditional meets contemporary.",
        **_price(1799.0, 0),
        "stock_quantity": 5,  # ← low stock intentional
        "available_sizes": ["XS", "S", "M", "L", "XL", "XXL"],
        "available_colors": ["Ivory", "Peach", "Sky Blue"],
        "image_urls": ["https://images.unsplash.com/photo-1610030469983-98e550d6193c?w=400"],
        "status": "active",
    },
    {
        "sku": "WOM-SWEATER-001",
        "name": "Chunky Knit Pullover Sweater",
        "brand": "KnitCo",
        "category": "Women",
        "description": "Oversized chunky knit in soft merino wool blend. Ribbed hem and cuffs.",
        **_price(2599.0, 15),
        "stock_quantity": 28,
        "available_sizes": ["XS/S", "M/L", "XL/XXL"],
        "available_colors": ["Oatmeal", "Caramel", "Dusty Rose"],
        "image_urls": ["https://images.unsplash.com/photo-1576566588028-4147f3842f27?w=400"],
        "status": "active",
    },

    # ── Kids ──────────────────────────────────────────────────────────────────
    {
        "sku": "KID-TSHIRT-001",
        "name": "Graphic Print Kids T-Shirt",
        "brand": "KidStyle",
        "category": "Kids",
        "description": "Fun graphic-print tee in breathable 100% cotton. Pre-shrunk fabric.",
        **_price(499.0, 0),
        "stock_quantity": 90,
        "available_sizes": ["2-3Y", "4-5Y", "6-7Y", "8-9Y", "10-11Y"],
        "available_colors": ["Red", "Blue", "Yellow", "Green"],
        "image_urls": ["https://images.unsplash.com/photo-1471286174890-9c112ffca5b4?w=400"],
        "status": "active",
    },
    {
        "sku": "KID-JEANS-001",
        "name": "Adjustable Waist Denim Jeans",
        "brand": "KidStyle",
        "category": "Kids",
        "description": "Rugged denim jeans with adjustable elastic waistband. Extra-reinforced knees.",
        **_price(799.0, 10),
        "stock_quantity": 70,
        "available_sizes": ["2-3Y", "4-5Y", "6-7Y", "8-9Y", "10-11Y"],
        "available_colors": ["Blue", "Dark Blue"],
        "image_urls": ["https://images.unsplash.com/photo-1519278409-1f56fdda7fe5?w=400"],
        "status": "active",
    },
    {
        "sku": "KID-DRESS-001",
        "name": "Princess Tulle Party Dress",
        "brand": "LittleAngel",
        "category": "Kids",
        "description": "Layered tulle party dress with satin bodice and bow detail.",
        **_price(1299.0, 0),
        "stock_quantity": 20,
        "available_sizes": ["2-3Y", "4-5Y", "6-7Y", "8-9Y"],
        "available_colors": ["Pink", "Purple", "White"],
        "image_urls": ["https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=400"],
        "status": "active",
    },
    {
        "sku": "KID-HOODIE-001",
        "name": "Zip-Up Fleece Hoodie",
        "brand": "KidCozy",
        "category": "Kids",
        "description": "Soft fleece zip-up hoodie with kangaroo pocket. Machine washable.",
        **_price(899.0, 0),
        "stock_quantity": 45,
        "available_sizes": ["4-5Y", "6-7Y", "8-9Y", "10-11Y", "12-13Y"],
        "available_colors": ["Grey", "Navy", "Red"],
        "image_urls": ["https://images.unsplash.com/photo-1622290291468-a28f7a7dc6a8?w=400"],
        "status": "active",
    },

    # ── Accessories ───────────────────────────────────────────────────────────
    {
        "sku": "ACC-BAG-001",
        "name": "Structured Leather Tote Bag",
        "brand": "LeatherCraft",
        "category": "Accessories",
        "description": "Hand-stitched genuine leather tote. Fits a 15\" laptop. Magnetic snap closure.",
        **_price(5999.0, 0),
        "stock_quantity": 18,
        "available_sizes": [],   # size-free: one size
        "available_colors": ["Tan", "Black", "Burgundy"],
        "image_urls": ["https://images.unsplash.com/photo-1548036328-c9fa89d128fa?w=400"],
        "status": "active",
    },
    {
        "sku": "ACC-WATCH-001",
        "name": "Minimalist Quartz Watch",
        "brand": "TimelessCo",
        "category": "Accessories",
        "description": "Ultra-thin quartz movement with sapphire crystal glass. 50m water-resistant.",
        **_price(4499.0, 10),
        "stock_quantity": 22,
        "available_sizes": [],
        "available_colors": ["Silver/White", "Gold/White", "Black/Black"],
        "image_urls": ["https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=400"],
        "status": "active",
    },
    {
        "sku": "ACC-BELT-001",
        "name": "Reversible Leather Belt",
        "brand": "LeatherCraft",
        "category": "Accessories",
        "description": "Genuine leather belt that reverses from black to brown. Nickel-free buckle.",
        **_price(1299.0, 0),
        "stock_quantity": 38,
        "available_sizes": ["S (28-30\")", "M (32-34\")", "L (36-38\")", "XL (40-42\")"],
        "available_colors": ["Black/Brown"],
        "image_urls": ["https://images.unsplash.com/photo-1624222247344-550fb60583dc?w=400"],
        "status": "active",
    },
    {
        "sku": "ACC-SCARF-001",
        "name": "Merino Wool Infinity Scarf",
        "brand": "KnitCo",
        "category": "Accessories",
        "description": "Super-soft 100% merino wool infinity scarf. Naturally temperature-regulating.",
        **_price(999.0, 0),
        "stock_quantity": 3,  # ← low stock intentional
        "available_sizes": [],
        "available_colors": ["Charcoal", "Camel", "Burgundy", "Forest Green"],
        "image_urls": ["https://images.unsplash.com/photo-1520903920243-00d872a2d1c9?w=400"],
        "status": "active",
    },
    {
        "sku": "ACC-CAP-001",
        "name": "Structured Baseball Cap",
        "brand": "HeadStyle",
        "category": "Accessories",
        "description": "Six-panel structured cap with adjustable snapback closure. 100% cotton.",
        **_price(699.0, 0),
        "stock_quantity": 55,
        "available_sizes": [],
        "available_colors": ["Black", "White", "Navy", "Olive"],
        "image_urls": ["https://images.unsplash.com/photo-1588850561407-ed78c282e89b?w=400"],
        "status": "active",
    },
    {
        "sku": "ACC-SUNGLASS-001",
        "name": "Polarized Aviator Sunglasses",
        "brand": "VisionStyle",
        "category": "Accessories",
        "description": "Classic aviator with polarized UV400 lenses and spring-hinge temples.",
        **_price(1899.0, 15),
        "stock_quantity": 30,
        "available_sizes": [],
        "available_colors": ["Gold/Green", "Silver/Grey", "Black/Smoke"],
        "image_urls": ["https://images.unsplash.com/photo-1572635196237-14b3f281503f?w=400"],
        "status": "active",
    },
    # Intentionally inactive product (tests filtering)
    {
        "sku": "MEN-SHIRT-DISC-001",
        "name": "Discontinued Linen Shirt",
        "brand": "ArrowFit",
        "category": "Men",
        "description": "End-of-line linen shirt. No longer available for sale.",
        **_price(999.0, 0),
        "stock_quantity": 0,
        "available_sizes": ["M", "L"],
        "available_colors": ["White"],
        "image_urls": [],
        "status": "inactive",
    },
]

# ── Sample Users and Orders ────────────────────────────────────────────────────

SAMPLE_USERS = [
    {"user_id": "seed-user-001", "name": "Aditya Sharma"},
    {"user_id": "seed-user-002", "name": "Priya Mehta"},
    {"user_id": "seed-user-003", "name": "Rohan Verma"},
]


# ── Database Operations ────────────────────────────────────────────────────────

async def seed_products(db: AsyncDatabase) -> Dict[str, str]:
    """Upsert all products and return a mapping of SKU → product_id string."""
    products_col = db["products"]
    sku_to_id: Dict[str, str] = {}

    for product in PRODUCTS:
        doc = {
            **product,
            "created_at": NOW,
            "updated_at": NOW,
        }
        result = await products_col.find_one_and_update(
            {"sku": product["sku"].upper()},
            {"$set": {**doc, "sku": product["sku"].upper()}},
            upsert=True,
            return_document=True,
        )
        sku_to_id[product["sku"].upper()] = str(result["_id"])

    print(f"  Products: {len(PRODUCTS)} upserted.")
    return sku_to_id


async def seed_inventory(db: AsyncDatabase, sku_to_id: Dict[str, str]) -> None:
    """Create/update inventory records for all products."""
    inventory_col = db["inventory"]

    for product in PRODUCTS:
        product_id = sku_to_id[product["sku"].upper()]
        qty = product["stock_quantity"]
        await inventory_col.find_one_and_update(
            {"product_id": product_id},
            {
                "$setOnInsert": {
                    "product_id": product_id,
                    "reserved": 0,
                    "low_stock_threshold": 10,
                    "last_updated": NOW,
                },
                "$set": {"quantity": qty},
            },
            upsert=True,
        )

    print(f"  Inventory: {len(PRODUCTS)} records upserted.")


async def seed_orders(db: AsyncDatabase, sku_to_id: Dict[str, str]) -> None:
    """Insert sample orders for each test user across various status stages."""
    orders_col = db["orders"]

    # Only seed orders if the collection is empty (avoid duplicating on re-runs)
    existing = await orders_col.count_documents({})
    if existing > 0:
        print(f"  Orders: {existing} already exist — skipping.")
        return

    # Pick a few known product IDs for orders
    shirt_id = sku_to_id.get("MEN-SHIRT-001")
    jeans_id = sku_to_id.get("MEN-JEANS-001")
    dress_id = sku_to_id.get("WOM-DRESS-001")
    watch_id = sku_to_id.get("ACC-WATCH-001")
    bag_id = sku_to_id.get("ACC-BAG-001")

    def _order(user_id: str, items: list, status: str, hours_ago: int = 0) -> dict:
        created = NOW - timedelta(hours=hours_ago)
        total = round(sum(i["subtotal"] for i in items), 2)
        return {
            "user_id": user_id,
            "items": items,
            "total": total,
            "item_count": sum(i["quantity"] for i in items),
            "status": status,
            "shipping_address": "123 Sample Street, Mumbai 400001",
            "notes": None,
            "status_notes": None,
            "created_at": created,
            "updated_at": created,
        }

    sample_orders = [
        # User 1: delivered order + pending order
        _order("seed-user-001", [
            {"product_id": shirt_id, "sku": "MEN-SHIRT-001", "name": "Classic Oxford Button-Down Shirt",
             "quantity": 2, "unit_price": 1169.1, "subtotal": 2338.2},
            {"product_id": jeans_id, "sku": "MEN-JEANS-001", "name": "Slim Fit Stretch Denim Jeans",
             "quantity": 1, "unit_price": 1999.2, "subtotal": 1999.2},
        ], status="delivered", hours_ago=72),

        _order("seed-user-001", [
            {"product_id": watch_id, "sku": "ACC-WATCH-001", "name": "Minimalist Quartz Watch",
             "quantity": 1, "unit_price": 4049.1, "subtotal": 4049.1},
        ], status="pending", hours_ago=2),

        # User 2: shipped order
        _order("seed-user-002", [
            {"product_id": dress_id, "sku": "WOM-DRESS-001", "name": "Floral Wrap Midi Dress",
             "quantity": 2, "unit_price": 1869.15, "subtotal": 3738.3},
        ], status="shipped", hours_ago=24),

        _order("seed-user-002", [
            {"product_id": bag_id, "sku": "ACC-BAG-001", "name": "Structured Leather Tote Bag",
             "quantity": 1, "unit_price": 5999.0, "subtotal": 5999.0},
        ], status="confirmed", hours_ago=8),

        # User 3: a cancelled order + a pending one
        _order("seed-user-003", [
            {"product_id": shirt_id, "sku": "MEN-SHIRT-001", "name": "Classic Oxford Button-Down Shirt",
             "quantity": 1, "unit_price": 1169.1, "subtotal": 1169.1},
        ], status="cancelled", hours_ago=48),

        _order("seed-user-003", [
            {"product_id": jeans_id, "sku": "MEN-JEANS-001", "name": "Slim Fit Stretch Denim Jeans",
             "quantity": 1, "unit_price": 1999.2, "subtotal": 1999.2},
            {"product_id": watch_id, "sku": "ACC-WATCH-001", "name": "Minimalist Quartz Watch",
             "quantity": 1, "unit_price": 4049.1, "subtotal": 4049.1},
        ], status="pending", hours_ago=1),
    ]

    await orders_col.insert_many(sample_orders)
    print(f"  Orders: {len(sample_orders)} inserted for {len(SAMPLE_USERS)} users.")


async def ensure_indexes(db: AsyncDatabase) -> None:
    """
    Ensure all required indexes exist (idempotent).

    These definitions mirror app/db/indexes.py exactly so that running this
    script against a fresh database produces the same index layout as the app.
    Calling create_index on an already-existing identical index is a no-op.
    """
    products_col = db["products"]
    inventory_col = db["inventory"]
    carts_col = db["carts"]
    orders_col = db["orders"]

    # Products — must match app/db/indexes.py _create_product_indexes()
    await products_col.create_index([("sku", ASCENDING)], unique=True, name="sku_unique")
    await products_col.create_index(
        [("category", ASCENDING), ("price", ASCENDING)],
        name="category_price",
    )
    await products_col.create_index([("brand", ASCENDING)], name="brand")
    await products_col.create_index([("status", ASCENDING)], name="status")
    await products_col.create_index([("price", ASCENDING)], name="price")
    await products_col.create_index([("created_at", DESCENDING)], name="created_at_desc")
    await products_col.create_index(
        [("name", TEXT), ("description", TEXT), ("brand", TEXT)],
        name="text_search",
        weights={"name": 10, "brand": 5, "description": 1},
    )

    # Inventory
    await inventory_col.create_index(
        [("product_id", ASCENDING)], unique=True, name="product_id_unique"
    )
    await inventory_col.create_index([("quantity", ASCENDING)], name="quantity")

    # Carts
    await carts_col.create_index([("user_id", ASCENDING)], unique=True, name="user_id_unique")

    # Orders — must match app/db/indexes.py _create_order_indexes()
    await orders_col.create_index(
        [("user_id", ASCENDING), ("created_at", DESCENDING)],
        name="user_id_created_at",
    )
    await orders_col.create_index([("status", ASCENDING)], name="status")

    print("  Indexes: ensured.")


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    print(f"\nConnecting to MongoDB: {MONGODB_URI} / {MONGODB_DATABASE}")
    client = AsyncMongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)

    try:
        await client.admin.command("ping")
        print("Connected.\n")
    except Exception as exc:
        print(f"ERROR: Cannot connect to MongoDB: {exc}")
        print("Make sure MongoDB is running or set MONGODB_URI correctly.")
        sys.exit(1)

    db = client[MONGODB_DATABASE]

    print("Seeding database...")
    await ensure_indexes(db)
    sku_to_id = await seed_products(db)
    await seed_inventory(db, sku_to_id)
    await seed_orders(db, sku_to_id)

    await client.close()

    print("\nDone! Your database is ready.")
    print(f"\nSummary:")
    print(f"  Products : {len(PRODUCTS)} ({len([p for p in PRODUCTS if p['status'] == 'active'])} active)")
    print(f"  Inventory: {len(PRODUCTS)} records")
    print(f"  Orders   : 6 across 3 users (pending, confirmed, shipped, delivered, cancelled)")
    print(f"\nAPI is available at: http://localhost:8000")
    print(f"Swagger docs       : http://localhost:8000/docs")
    low_stock = [p['sku'] for p in PRODUCTS if p['stock_quantity'] <= 10 and p['status'] == 'active']
    print(f"\nLow-stock products (will trigger alert job): {low_stock}")


if __name__ == "__main__":
    asyncio.run(main())
