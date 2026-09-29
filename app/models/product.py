"""
app/models/product.py

Internal (domain) model for a Product document stored in MongoDB.

'Models' in this project represent the shape of data as it lives in
the database.  They are separate from 'Schemas' (in app/schemas/)
which represent the shape of data as it enters or leaves the API.

This separation exists because:
- MongoDB stores `_id` (ObjectId); the API exposes `id` (string).
- Some fields (e.g. final_price) are computed and never stored.
- Internal fields like `created_at` / `updated_at` are not writable
  via the API but are always present in the database document.
"""

# Placeholder — full implementation in Stage 2.
