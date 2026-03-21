# Sample E-Commerce Backend

A simple FastAPI backend with sample product data for prototyping and testing.

## Setup

```bash
pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8000
```

API docs: [http://localhost:8000/docs](http://localhost:8000/docs)

## Endpoints

| Method | Endpoint                    | Description                        |
| ------ | --------------------------- | ---------------------------------- |
| GET    | `/categories`               | List all categories                |
| GET    | `/categories/{id}`          | Get a category by ID               |
| GET    | `/products`                 | List products (with filters below) |
| GET    | `/products/{id}`            | Get a product by ID                |
| GET    | `/products/{id}/related`    | Related products in same category  |
| GET    | `/brands`                   | List unique brand names            |
| POST   | `/cart`                     | Create a new cart                  |
| GET    | `/cart/{cart_id}`           | View cart contents                 |
| POST   | `/cart/{cart_id}/items`     | Add item to cart                   |
| DELETE | `/cart/{cart_id}/items/{id}`| Remove item from cart              |
| POST   | `/cart/{cart_id}/checkout`  | Checkout → get order_id + total    |
| GET    | `/orders/{order_id}`       | Check order status                 |
| POST   | `/payments/confirm`        | Payment confirmation (from :5000)  |

## Product Filters

All query parameters on `GET /products` are optional:

| Param        | Type    | Description                          |
| ------------ | ------- | ------------------------------------ |
| `category_id`| int     | Filter by category                   |
| `brand`      | string  | Filter by brand (case-insensitive)   |
| `min_price`  | float   | Minimum price                        |
| `max_price`  | float   | Maximum price                        |
| `min_rating` | float   | Minimum rating (0–5)                 |
| `in_stock`   | bool    | Only items with stock > 0            |
| `search`     | string  | Search name and description          |
| `sort_by`    | string  | `price`, `rating`, or `name`         |
| `order`      | string  | `asc` (default) or `desc`            |
| `page`       | int     | Page number (default 1)              |
| `page_size`  | int     | Items per page (1–100, default 10)   |

## Examples

```bash
# All electronics, sorted by price descending
curl "http://localhost:8000/products?category_id=1&sort_by=price&order=desc"

# Search for "keyboard"
curl "http://localhost:8000/products?search=keyboard"

# Products under $30 with rating >= 4.5
curl "http://localhost:8000/products?max_price=30&min_rating=4.5"

# Brands in the Clothing category
curl "http://localhost:8000/brands?category_id=2"

# Products related to product #3
curl "http://localhost:8000/products/3/related"
```

## Sample Data

25 products across 5 categories: Electronics, Clothing, Home & Kitchen, Books, and Sports & Outdoors.

## Purchase Flow

```
User                      This backend (:8000)           Payments backend (:5000)
 │                              │                                │
 ├─ POST /cart ────────────────►│  (creates cart)                │
 ├─ POST /cart/{id}/items ─────►│  (adds products)               │
 ├─ POST /cart/{id}/checkout ──►│  (returns order_id + total)    │
 │                              │                                │
 ├─ POST /pay ─────────────────────────────────────────────────►│
 │   { order_id, amount }       │                                │
 │                              │◄── POST /payments/confirm ─────┤
 │                              │   { order_id, status }         │
 │                              │   (reduces stock if success)   │
```

### Example: full purchase

```bash
# 1. Create a cart
curl -s -X POST http://localhost:8000/cart
# → { "cart_id": "a1b2c3d4e5f6" }

# 2. Add items
curl -s -X POST http://localhost:8000/cart/a1b2c3d4e5f6/items \
  -H "Content-Type: application/json" \
  -d '{"product_id": 3, "quantity": 1}'

curl -s -X POST http://localhost:8000/cart/a1b2c3d4e5f6/items \
  -H "Content-Type: application/json" \
  -d '{"product_id": 19, "quantity": 2}'

# 3. View cart
curl -s http://localhost:8000/cart/a1b2c3d4e5f6

# 4. Checkout
curl -s -X POST http://localhost:8000/cart/a1b2c3d4e5f6/checkout
# → { "order_id": "abc123...", "total": 123.97, "message": "..." }

# 5. (User pays via sham payments backend on :5000)

# 6. Payments backend confirms to us:
curl -s -X POST http://localhost:8000/payments/confirm \
  -H "Content-Type: application/json" \
  -d '{"order_id": "abc123...", "status": "success"}'
# → { "order_id": "abc123...", "status": "paid", "message": "Payment confirmed. Stock updated." }

# 7. Check order status
curl -s http://localhost:8000/orders/abc123...
```

### Payment confirmation endpoint (for your sham payments backend)

Your payments backend on `:5000` should call this after processing a payment:

```
POST http://localhost:8000/payments/confirm
Content-Type: application/json

{
  "order_id": "<the order_id string the user gave you>",
  "status": "success"   // or "failed"
}
```

**Response on success:**
```json
{ "order_id": "...", "status": "paid", "message": "Payment confirmed. Stock updated." }
```

**Response on failure:**
```json
{ "order_id": "...", "status": "payment_failed", "message": "Payment failed. Order not fulfilled." }
```
