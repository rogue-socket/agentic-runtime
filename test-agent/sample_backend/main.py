import uuid

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from data import CATEGORIES, PRODUCTS


# ---------- In-memory stores ----------

# carts: { cart_id: { product_id: quantity, ... } }
CARTS: dict[str, dict[int, int]] = {}

# orders: { order_id: { "cart_id", "items", "total", "status" } }
ORDERS: dict[str, dict] = {}


# ---------- Request models ----------

class CartItem(BaseModel):
    product_id: int
    quantity: int = 1


class PaymentConfirmation(BaseModel):
    order_id: str
    status: str  # "success" or "failed"

app = FastAPI(title="Sample E-Commerce API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Categories ----------

@app.get("/categories")
def get_categories():
    """Return all product categories."""
    return CATEGORIES


@app.get("/categories/{category_id}")
def get_category(category_id: int):
    """Return a single category by ID."""
    for cat in CATEGORIES:
        if cat["id"] == category_id:
            return cat
    return {"error": "Category not found"}, 404


# ---------- Products ----------

@app.get("/products")
def get_products(
    category_id: int | None = Query(None, description="Filter by category ID"),
    brand: str | None = Query(None, description="Filter by brand name (case-insensitive)"),
    min_price: float | None = Query(None, ge=0, description="Minimum price"),
    max_price: float | None = Query(None, ge=0, description="Maximum price"),
    min_rating: float | None = Query(None, ge=0, le=5, description="Minimum rating (0-5)"),
    in_stock: bool | None = Query(None, description="Only show items in stock"),
    search: str | None = Query(None, description="Search product name or description"),
    sort_by: str | None = Query(None, description="Sort field: price, rating, name"),
    order: str = Query("asc", description="Sort order: asc or desc"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(10, ge=1, le=100, description="Items per page"),
):
    """Return products with optional filters, search, sorting, and pagination."""
    results = list(PRODUCTS)

    # --- Filters ---
    if category_id is not None:
        results = [p for p in results if p["category_id"] == category_id]

    if brand is not None:
        results = [p for p in results if p["brand"].lower() == brand.lower()]

    if min_price is not None:
        results = [p for p in results if p["price"] >= min_price]

    if max_price is not None:
        results = [p for p in results if p["price"] <= max_price]

    if min_rating is not None:
        results = [p for p in results if p["rating"] >= min_rating]

    if in_stock is True:
        results = [p for p in results if p["stock"] > 0]

    if search is not None:
        q = search.lower()
        results = [
            p for p in results
            if q in p["name"].lower() or q in p["description"].lower()
        ]

    # --- Sorting ---
    if sort_by in ("price", "rating", "name"):
        reverse = order.lower() == "desc"
        results = sorted(results, key=lambda p: p[sort_by], reverse=reverse)

    # --- Pagination ---
    total = len(results)
    start = (page - 1) * page_size
    end = start + page_size
    page_items = results[start:end]

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "products": page_items,
    }


@app.get("/products/{product_id}")
def get_product(product_id: int):
    """Return a single product by ID, including its category info."""
    for prod in PRODUCTS:
        if prod["id"] == product_id:
            category = next(
                (c for c in CATEGORIES if c["id"] == prod["category_id"]), None
            )
            return {**prod, "category": category}
    return {"error": "Product not found"}, 404


@app.get("/brands")
def get_brands(category_id: int | None = Query(None, description="Filter brands by category")):
    """Return a list of unique brand names, optionally filtered by category."""
    products = PRODUCTS
    if category_id is not None:
        products = [p for p in products if p["category_id"] == category_id]
    return sorted({p["brand"] for p in products})


@app.get("/products/{product_id}/related")
def get_related_products(product_id: int, limit: int = Query(4, ge=1, le=20)):
    """Return products in the same category (excluding the given product)."""
    source = next((p for p in PRODUCTS if p["id"] == product_id), None)
    if source is None:
        return {"error": "Product not found"}, 404
    related = [
        p for p in PRODUCTS
        if p["category_id"] == source["category_id"] and p["id"] != product_id
    ]
    return related[:limit]


# ---------- Cart ----------

@app.post("/cart")
def create_cart():
    """Create a new empty cart. Returns the cart_id."""
    cart_id = uuid.uuid4().hex[:12]
    CARTS[cart_id] = {}
    return {"cart_id": cart_id}


@app.get("/cart/{cart_id}")
def get_cart(cart_id: str):
    """View the contents of a cart."""
    if cart_id not in CARTS:
        raise HTTPException(status_code=404, detail="Cart not found")

    items = []
    total = 0.0
    for product_id, qty in CARTS[cart_id].items():
        product = next((p for p in PRODUCTS if p["id"] == product_id), None)
        if product:
            line_total = round(product["price"] * qty, 2)
            total += line_total
            items.append({
                "product_id": product["id"],
                "name": product["name"],
                "price": product["price"],
                "quantity": qty,
                "line_total": line_total,
            })
    return {"cart_id": cart_id, "items": items, "total": round(total, 2)}


@app.post("/cart/{cart_id}/items")
def add_to_cart(cart_id: str, item: CartItem):
    """Add a product to the cart (or increase its quantity)."""
    if cart_id not in CARTS:
        raise HTTPException(status_code=404, detail="Cart not found")

    product = next((p for p in PRODUCTS if p["id"] == item.product_id), None)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    if item.quantity < 1:
        raise HTTPException(status_code=400, detail="Quantity must be at least 1")

    current_qty = CARTS[cart_id].get(item.product_id, 0)
    new_qty = current_qty + item.quantity
    if new_qty > product["stock"]:
        raise HTTPException(status_code=400, detail=f"Not enough stock (available: {product['stock']})")

    CARTS[cart_id][item.product_id] = new_qty
    return {"cart_id": cart_id, "product_id": item.product_id, "quantity": new_qty}


@app.delete("/cart/{cart_id}/items/{product_id}")
def remove_from_cart(cart_id: str, product_id: int):
    """Remove a product from the cart entirely."""
    if cart_id not in CARTS:
        raise HTTPException(status_code=404, detail="Cart not found")
    if product_id not in CARTS[cart_id]:
        raise HTTPException(status_code=404, detail="Item not in cart")

    del CARTS[cart_id][product_id]
    return {"cart_id": cart_id, "removed_product_id": product_id}


# ---------- Checkout / Buy ----------

@app.post("/cart/{cart_id}/checkout")
def checkout(cart_id: str):
    """
    Finalize the cart into an order.
    Returns a unique order_id and the total amount.
    The user should send these to the payments backend (localhost:5000) to pay.
    """
    if cart_id not in CARTS:
        raise HTTPException(status_code=404, detail="Cart not found")
    if not CARTS[cart_id]:
        raise HTTPException(status_code=400, detail="Cart is empty")

    # Build line items and total
    items = []
    total = 0.0
    for product_id, qty in CARTS[cart_id].items():
        product = next((p for p in PRODUCTS if p["id"] == product_id), None)
        if product is None:
            raise HTTPException(status_code=400, detail=f"Product {product_id} no longer exists")
        if qty > product["stock"]:
            raise HTTPException(status_code=400, detail=f"Not enough stock for '{product['name']}' (requested {qty}, available {product['stock']})")
        line_total = round(product["price"] * qty, 2)
        total += line_total
        items.append({"product_id": product_id, "quantity": qty, "price": product["price"], "line_total": line_total})

    order_id = uuid.uuid4().hex
    ORDERS[order_id] = {
        "cart_id": cart_id,
        "items": items,
        "total": round(total, 2),
        "status": "pending_payment",
    }

    return {
        "order_id": order_id,
        "total": round(total, 2),
        "message": "Send order_id and total to the payments backend to complete purchase.",
    }


@app.get("/orders/{order_id}")
def get_order(order_id: str):
    """Check the status of an order."""
    if order_id not in ORDERS:
        raise HTTPException(status_code=404, detail="Order not found")
    return {"order_id": order_id, **ORDERS[order_id]}


# ---------- Payment confirmation (called by sham payments backend) ----------

@app.post("/payments/confirm")
def confirm_payment(confirmation: PaymentConfirmation):
    """
    Endpoint for the sham payments backend (localhost:5000) to call
    after a payment is processed.

    Expects: { "order_id": "...", "status": "success" | "failed" }

    On success: reduces stock for each item and marks the order as paid.
    On failure: marks the order as payment_failed.
    """
    if confirmation.order_id not in ORDERS:
        raise HTTPException(status_code=404, detail="Order not found")

    order = ORDERS[confirmation.order_id]

    if order["status"] != "pending_payment":
        raise HTTPException(status_code=400, detail=f"Order already processed (status: {order['status']})")

    if confirmation.status == "success":
        # Reduce inventory
        for item in order["items"]:
            product = next((p for p in PRODUCTS if p["id"] == item["product_id"]), None)
            if product:
                product["stock"] = max(0, product["stock"] - item["quantity"])
        order["status"] = "paid"
        # Clean up the cart
        CARTS.pop(order["cart_id"], None)
        return {"order_id": confirmation.order_id, "status": "paid", "message": "Payment confirmed. Stock updated."}
    else:
        order["status"] = "payment_failed"
        return {"order_id": confirmation.order_id, "status": "payment_failed", "message": "Payment failed. Order not fulfilled."}
