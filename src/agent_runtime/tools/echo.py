from __future__ import annotations

"""File: src/agent_runtime/tools/echo.py

Purpose:
Provide a deterministic built-in echo tool for examples and tests.

Description:
Returns input message as output without external side effects, making it
safe for runtime smoke checks and reproducible test execution.

The `message` field accepts any JSON-serializable value. Non-string values
(dicts, lists, numbers, booleans) are coerced to a pretty-printed JSON string
before being returned, so downstream steps and logging always receive a string.
"""

import json
from typing import Any, Dict, Optional

from .base import RuntimeContext, ToolResult


class EchoTool:
    """Simple tool that echoes back provided `message` field.

    Accepts any JSON-serializable value for `message`. Non-string values are
    serialized to indented JSON automatically.
    """

    name = "tools.echo"
    description = "Returns the provided input, serializing non-string values to JSON"
    input_schema = {
        "type": "object",
        "properties": {
            # Accept any type — the tool normalizes non-strings to JSON strings.
            "message": {}
        },
    }
    timeout: Optional[float] = None
    retries: Optional[int] = None

    async def execute(self, input: Dict[str, Any], context: RuntimeContext) -> ToolResult:
        """Return successful tool result containing the input message.

        Non-string message values (dict, list, int, float, bool) are serialized
        to an indented JSON string so the output is always human-readable.
        """
        raw = input.get("message")
        if isinstance(raw, str):
            message = raw
        else:
            message = json.dumps(raw, indent=2, ensure_ascii=False)
        return ToolResult(success=True, output={"message": message}, error=None, metadata=None)
