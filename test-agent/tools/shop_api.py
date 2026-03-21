"""Tools for interacting with the e-commerce shop backend on localhost:8000."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, Optional
from urllib.parse import urlencode

from agent_runtime.tools.base import RuntimeContext, ToolResult

SHOP_BASE = "http://localhost:8000"


def _shop_request(
    path: str,
    method: str = "GET",
    json_body: Optional[dict] = None,
) -> dict:
    """Make an HTTP request to the shop backend and return parsed JSON."""
    url = f"{SHOP_BASE}{path}"
    data = None
    headers = {}
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"error": f"HTTP {exc.code}", "body": body}
    except urllib.error.URLError as exc:
        return {"error": f"Connection failed: {exc.reason}"}


class ShopListProducts:
    """List products from the shop, with optional filters."""

    name = "tools.shop_list_products"
    description = (
        "List products from the online shop. Supports filters: "
        "category_id, brand, min_price, max_price, min_rating, in_stock, "
        "search, sort_by (price|rating|name), order (asc|desc), page, page_size."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "category_id": {"type": "integer", "description": "Filter by category ID"},
            "brand": {"type": "string", "description": "Filter by brand name"},
            "min_price": {"type": "number", "description": "Minimum price filter"},
            "max_price": {"type": "number", "description": "Maximum price filter"},
            "min_rating": {"type": "number", "description": "Minimum rating (0-5)"},
            "in_stock": {"type": "boolean", "description": "Only in-stock items"},
            "search": {"type": "string", "description": "Search name/description"},
            "sort_by": {"type": "string", "enum": ["price", "rating", "name"]},
            "order": {"type": "string", "enum": ["asc", "desc"]},
            "page": {"type": "integer", "description": "Page number"},
            "page_size": {"type": "integer", "description": "Items per page (1-100)"},
        },
        "required": [],
    }
    timeout: Optional[float] = 15.0
    retries: Optional[int] = 1

    async def execute(self, input: Dict[str, Any], context: RuntimeContext) -> ToolResult:
        params = {k: v for k, v in input.items() if v is not None}
        qs = f"?{urlencode(params)}" if params else ""
        result = _shop_request(f"/products{qs}")
        if "error" in result:
            return ToolResult(success=False, output=result, error=result["error"], metadata=None)
        return ToolResult(success=True, output=result, error=None, metadata=None)


class ShopGetProduct:
    """Get details of a single product by ID."""

    name = "tools.shop_get_product"
    description = "Get full details for a specific product by its ID."
    input_schema = {
        "type": "object",
        "properties": {
            "product_id": {"type": "integer", "description": "The product ID to look up"},
        },
        "required": ["product_id"],
    }
    timeout: Optional[float] = 15.0
    retries: Optional[int] = 1

    async def execute(self, input: Dict[str, Any], context: RuntimeContext) -> ToolResult:
        pid = input["product_id"]
        result = _shop_request(f"/products/{pid}")
        if "error" in result:
            return ToolResult(success=False, output=result, error=result["error"], metadata=None)
        return ToolResult(success=True, output=result, error=None, metadata=None)


class ShopCreateCart:
    """Create a new shopping cart."""

    name = "tools.shop_create_cart"
    description = "Create a new empty shopping cart. Returns a cart_id."
    input_schema = {
        "type": "object",
        "properties": {},
        "required": [],
    }
    timeout: Optional[float] = 15.0
    retries: Optional[int] = 1

    async def execute(self, input: Dict[str, Any], context: RuntimeContext) -> ToolResult:
        result = _shop_request("/cart", method="POST")
        if "error" in result:
            return ToolResult(success=False, output=result, error=result["error"], metadata=None)
        return ToolResult(success=True, output=result, error=None, metadata=None)


class ShopAddToCart:
    """Add a product to a cart."""

    name = "tools.shop_add_to_cart"
    description = "Add a product to an existing cart. Requires cart_id, product_id, and quantity."
    input_schema = {
        "type": "object",
        "properties": {
            "cart_id": {"type": "string", "description": "The cart ID"},
            "product_id": {"type": "integer", "description": "Product ID to add"},
            "quantity": {"type": "integer", "description": "Quantity to add", "minimum": 1},
        },
        "required": ["cart_id", "product_id", "quantity"],
    }
    timeout: Optional[float] = 15.0
    retries: Optional[int] = 1

    async def execute(self, input: Dict[str, Any], context: RuntimeContext) -> ToolResult:
        cart_id = input["cart_id"]
        body = {"product_id": input["product_id"], "quantity": input["quantity"]}
        result = _shop_request(f"/cart/{cart_id}/items", method="POST", json_body=body)
        if "error" in result:
            return ToolResult(success=False, output=result, error=result["error"], metadata=None)
        return ToolResult(success=True, output=result, error=None, metadata=None)


class ShopCheckout:
    """Checkout a cart to get an order_id and total."""

    name = "tools.shop_checkout"
    description = "Checkout a cart. Returns order_id and total amount to pay."
    input_schema = {
        "type": "object",
        "properties": {
            "cart_id": {"type": "string", "description": "The cart ID to checkout"},
        },
        "required": ["cart_id"],
    }
    timeout: Optional[float] = 15.0
    retries: Optional[int] = 1

    async def execute(self, input: Dict[str, Any], context: RuntimeContext) -> ToolResult:
        cart_id = input["cart_id"]
        result = _shop_request(f"/cart/{cart_id}/checkout", method="POST")
        if "error" in result:
            return ToolResult(success=False, output=result, error=result["error"], metadata=None)
        return ToolResult(success=True, output=result, error=None, metadata=None)


class ShopGetOrder:
    """Check the status of an order."""

    name = "tools.shop_get_order"
    description = "Check the current status of an order by order_id."
    input_schema = {
        "type": "object",
        "properties": {
            "order_id": {"type": "string", "description": "The order ID to check"},
        },
        "required": ["order_id"],
    }
    timeout: Optional[float] = 15.0
    retries: Optional[int] = 1

    async def execute(self, input: Dict[str, Any], context: RuntimeContext) -> ToolResult:
        order_id = input["order_id"]
        result = _shop_request(f"/orders/{order_id}")
        if "error" in result:
            return ToolResult(success=False, output=result, error=result["error"], metadata=None)
        return ToolResult(success=True, output=result, error=None, metadata=None)
