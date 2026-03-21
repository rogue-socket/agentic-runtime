"""Tools for interacting with the payment/banking backend on localhost:5000."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from agent_runtime.tools.base import RuntimeContext, ToolResult

BANK_BASE = "http://localhost:5000"


def _bank_request(
    path: str,
    method: str = "GET",
    json_body: Optional[dict] = None,
) -> dict:
    """Make an HTTP request to the payment backend and return parsed JSON."""
    url = f"{BANK_BASE}{path}"
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


class BankCheckBalance:
    """Check the bank account balance."""

    name = "tools.bank_check_balance"
    description = "Check the current balance of the bank account."
    input_schema = {
        "type": "object",
        "properties": {},
        "required": [],
    }
    timeout: Optional[float] = 15.0
    retries: Optional[int] = 1

    async def execute(self, input: Dict[str, Any], context: RuntimeContext) -> ToolResult:
        result = _bank_request("/balance")
        if "error" in result:
            return ToolResult(success=False, output=result, error=result["error"], metadata=None)
        return ToolResult(success=True, output=result, error=None, metadata=None)


class BankPayOrder:
    """Pay for a shop order. Sends payment and triggers shop confirmation."""

    name = "tools.bank_pay_order"
    description = (
        "Pay for a shop order. Provide the order_id from checkout and the amount. "
        "The payment backend will deduct funds and automatically confirm with the shop."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "order_id": {"type": "string", "description": "Order ID from shop checkout"},
            "amount": {"type": "number", "description": "Total amount to pay"},
        },
        "required": ["order_id", "amount"],
    }
    timeout: Optional[float] = 15.0
    retries: Optional[int] = 1

    async def execute(self, input: Dict[str, Any], context: RuntimeContext) -> ToolResult:
        body = {"order_id": input["order_id"], "amount": input["amount"]}
        result = _bank_request("/pay/order", method="POST", json_body=body)
        if "error" in result:
            return ToolResult(success=False, output=result, error=result["error"], metadata=None)
        if result.get("status") == "failed":
            return ToolResult(
                success=False, output=result, error=result.get("message", "Payment failed"), metadata=None
            )
        return ToolResult(success=True, output=result, error=None, metadata=None)


class BankGetTransactions:
    """View transaction history."""

    name = "tools.bank_get_transactions"
    description = "View the full transaction history of the bank account."
    input_schema = {
        "type": "object",
        "properties": {},
        "required": [],
    }
    timeout: Optional[float] = 15.0
    retries: Optional[int] = 1

    async def execute(self, input: Dict[str, Any], context: RuntimeContext) -> ToolResult:
        result = _bank_request("/transactions")
        if "error" in result:
            return ToolResult(success=False, output=result, error=result["error"], metadata=None)
        return ToolResult(success=True, output=result, error=None, metadata=None)
