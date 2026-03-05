from __future__ import annotations

from typing import Any, Dict, Optional

from .base import RuntimeContext, ToolResult


class EchoTool:
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
        return ToolResult(success=True, output={"message": input.get("message")}, error=None, metadata=None)
