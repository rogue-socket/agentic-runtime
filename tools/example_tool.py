"""Example tool module.

The runtime auto-discovers tools from the tools/ directory.

Discovery convention: every class that implements the Tool protocol (has
``name``, ``description``, ``input_schema``, and ``execute``) and whose
class name does not start with ``_`` is instantiated and registered.

Tool protocol requirements:
  - name: str           (e.g. "tools.example")
  - description: str
  - input_schema: dict  (JSON Schema for input validation)
  - timeout: Optional[float]
  - retries: Optional[int]
  - async execute(input, context) -> ToolResult
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from agent_runtime.tools.base import RuntimeContext, ToolResult


class ExampleTool:
    """Example tool that uppercases a message.

    Usage in workflow YAML:
        - id: my_step
          type: tool
          tool: tools.example
          inputs:
            text: inputs.text
    """

    name = "tools.example"
    description = "Uppercases the provided text"
    input_schema = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
        },
    }
    timeout: Optional[float] = None
    retries: Optional[int] = None

    async def execute(
        self, input: Dict[str, Any], context: RuntimeContext
    ) -> ToolResult:
        # TODO: Replace with real tool logic (e.g. API call).
        text = input.get("text", "")
        return ToolResult(
            success=True,
            output={"text": text.upper()},
            error=None,
            metadata=None,
        )
