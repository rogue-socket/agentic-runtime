from __future__ import annotations

"""File: src/agent_runtime/tools/echo.py

Purpose:
Provide a deterministic built-in echo tool for examples and tests.

Description:
Returns input message as output without external side effects, making it
safe for runtime smoke checks and reproducible test execution.
"""

from typing import Any, Dict, Optional

from .base import RuntimeContext, ToolResult


class EchoTool:
    """Simple tool that echoes back provided `message` field."""

    name = "tools.echo"
    description = "Returns the provided input"
    input_schema = {
        "type": "object",
        "properties": {
            "message": {"type": "string"}
        },
    }
    timeout: Optional[float] = None
    retries: Optional[int] = None

    async def execute(self, input: Dict[str, Any], context: RuntimeContext) -> ToolResult:
        """Return successful tool result containing the input message."""
        return ToolResult(success=True, output={"message": input.get("message")}, error=None, metadata=None)
