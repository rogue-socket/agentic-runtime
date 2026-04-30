"""Mock shop tools for the shopping agent example.

These tools simulate a shop backend with product catalog, cart, and checkout.
All data is in-memory (not persisted).
"""

from __future__ import annotations
from typing import Any
import json
import time

# In-memory shop state
_PRODUCTS = {
    "BOOK001": {"id": "BOOK001", "name": "The Pragmatic Programmer", "price": 49.99, "category": "books"},
    "BOOK002": {"id": "BOOK002", "name": "Python Cookbook", "price": 39.99, "category": "books"},
    "PEN001": {"id": "PEN001", "name": "Premium Ballpoint Pen", "price": 12.99, "category": "stationery"},
    "PEN002": {"id": "PEN002", "name": "Fountain Pen Set", "price": 24.99, "category": "stationery"},
    "NOTE001": {"id": "NOTE001", "name": "Leather Notebook", "price": 29.99, "category": "stationery"},
}

_CARTS = {}  # {cart_id: {"items": [{"product_id": str, "quantity": int}], "created": timestamp}}
_ORDERS = {}  # {order_id: {"cart_id": str, "status": str, "total": float}}


def shop_list_products(query: str | None = None) -> dict[str, Any]:
    """List products in the shop, optionally filtered by search query.

    Args:
        query: Optional search term to filter products.

    Returns:
        List of products matching the query.
    """
    products = list(_PRODUCTS.values())

    if query:
        query_lower = query.lower()
        products = [p for p in products if query_lower in p["name"].lower() or query_lower in p["category"].lower()]

    return {"products": products, "count": len(products)}


def shop_get_product(product_id: str) -> dict[str, Any]:
    """Get details for a specific product.

    Args:
        product_id: The product ID.

    Returns:
        Product details if found, error dict otherwise.
    """
    if product_id in _PRODUCTS:
        return _PRODUCTS[product_id]
    return {"error": f"Product {product_id} not found"}


def shop_create_cart() -> dict[str, Any]:
    """Create a new shopping cart.

    Returns:
        Cart ID for the newly created cart.
    """
    cart_id = f"CART-{int(time.time() * 1000)}"
    _CARTS[cart_id] = {"items": [], "created": time.time()}
    return {"cart_id": cart_id}


def shop_add_to_cart(cart_id: str, product_id: str, quantity: int = 1) -> dict[str, Any]:
    """Add an item to a cart.

    Args:
        cart_id: The cart ID.
        product_id: The product to add.
        quantity: Quantity to add (default: 1).

    Returns:
        Updated cart with all items.
    """
    if cart_id not in _CARTS:
        return {"error": f"Cart {cart_id} not found"}

    if product_id not in _PRODUCTS:
        return {"error": f"Product {product_id} not found"}

    cart = _CARTS[cart_id]
    # Check if product already in cart
    item_found = False
    for item in cart["items"]:
        if item["product_id"] == product_id:
            item["quantity"] += quantity
            item_found = True
            break

    if not item_found:
        cart["items"].append({"product_id": product_id, "quantity": quantity})

    # Calculate total
    total = sum(_PRODUCTS[item["product_id"]]["price"] * item["quantity"] for item in cart["items"])

    return {
        "cart_id": cart_id,
        "items": cart["items"],
        "item_count": len(cart["items"]),
        "total": round(total, 2),
    }


def shop_checkout(cart_id: str) -> dict[str, Any]:
    """Checkout a cart and create an order.

    Args:
        cart_id: The cart to checkout.

    Returns:
        Order ID, order status, and total amount.
    """
    if cart_id not in _CARTS:
        return {"error": f"Cart {cart_id} not found"}

    cart = _CARTS[cart_id]
    if not cart["items"]:
        return {"error": "Cart is empty"}

    order_id = f"ORD-{int(time.time() * 1000)}"
    total = sum(_PRODUCTS[item["product_id"]]["price"] * item["quantity"] for item in cart["items"])

    _ORDERS[order_id] = {
        "cart_id": cart_id,
        "status": "pending_payment",
        "total": round(total, 2),
        "items": cart["items"],
    }

    items_desc = ", ".join(
        f"{_PRODUCTS[item['product_id']]['name']} (qty: {item['quantity']})"
        for item in cart["items"]
    )

    return {
        "order_id": order_id,
        "status": "pending_payment",
        "total": round(total, 2),
        "items": items_desc,
    }
