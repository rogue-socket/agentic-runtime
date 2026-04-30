"""Tool wrappers for shop operations.

These wrap the mock shop functions into ForrestRun tool classes.
"""

from __future__ import annotations
from typing import Any, Dict, Optional
import json

from agent_runtime.tools.base import RuntimeContext, ToolResult
from . import shop


class ShopListProductsTool:
    name = "tools.shop_list_products"
    description = "List products in the shop, optionally filtered by search query"
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Optional search term to filter products",
            }
        },
    }
    timeout: Optional[float] = None
    retries: Optional[int] = None

    async def execute(self, input: Dict[str, Any], context: RuntimeContext) -> ToolResult:
        try:
            result = shop.shop_list_products(query=input.get("query"))
            return ToolResult(success=True, output=result, error=None, metadata=None)
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e), metadata=None)


class ShopGetProductTool:
    name = "tools.shop_get_product"
    description = "Get details for a specific product by ID"
    input_schema = {
        "type": "object",
        "properties": {
            "product_id": {
                "type": "string",
                "description": "The product ID",
            }
        },
        "required": ["product_id"],
    }
    timeout: Optional[float] = None
    retries: Optional[int] = None

    async def execute(self, input: Dict[str, Any], context: RuntimeContext) -> ToolResult:
        try:
            result = shop.shop_get_product(input["product_id"])
            return ToolResult(success=True, output=result, error=None, metadata=None)
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e), metadata=None)


class ShopCreateCartTool:
    name = "tools.shop_create_cart"
    description = "Create a new shopping cart"
    input_schema = {
        "type": "object",
        "properties": {},
    }
    timeout: Optional[float] = None
    retries: Optional[int] = None

    async def execute(self, input: Dict[str, Any], context: RuntimeContext) -> ToolResult:
        try:
            result = shop.shop_create_cart()
            return ToolResult(success=True, output=result, error=None, metadata=None)
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e), metadata=None)


class ShopAddToCartTool:
    name = "tools.shop_add_to_cart"
    description = "Add an item to a shopping cart"
    input_schema = {
        "type": "object",
        "properties": {
            "cart_id": {
                "type": "string",
                "description": "The cart ID",
            },
            "product_id": {
                "type": "string",
                "description": "The product to add",
            },
            "quantity": {
                "type": "integer",
                "description": "Quantity to add (default: 1)",
                "default": 1,
            },
        },
        "required": ["cart_id", "product_id"],
    }
    timeout: Optional[float] = None
    retries: Optional[int] = None

    async def execute(self, input: Dict[str, Any], context: RuntimeContext) -> ToolResult:
        try:
            result = shop.shop_add_to_cart(
                input["cart_id"],
                input["product_id"],
                quantity=input.get("quantity", 1),
            )
            return ToolResult(success=True, output=result, error=None, metadata=None)
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e), metadata=None)


class ShopCheckoutTool:
    name = "tools.shop_checkout"
    description = "Checkout a cart and create an order"
    input_schema = {
        "type": "object",
        "properties": {
            "cart_id": {
                "type": "string",
                "description": "The cart to checkout",
            }
        },
        "required": ["cart_id"],
    }
    timeout: Optional[float] = None
    retries: Optional[int] = None

    async def execute(self, input: Dict[str, Any], context: RuntimeContext) -> ToolResult:
        try:
            result = shop.shop_checkout(input["cart_id"])
            return ToolResult(success=True, output=result, error=None, metadata=None)
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e), metadata=None)
