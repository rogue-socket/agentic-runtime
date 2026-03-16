from __future__ import annotations

"""File: src/agent_runtime/tools/base.py

Purpose:
Define tool execution contracts used by the runtime.

Description:
Contains dataclasses and protocol describing tool invocation input,
result payloads, and runtime context metadata passed to tools.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol


@dataclass
class ToolResult:
    """Standard tool result envelope.

    Example:
        >>> ToolResult(success=True, output={}, error=None, metadata=None).success
        True
    """
    success: bool
    output: Optional[Dict[str, Any]]
    error: Optional[str]
    metadata: Optional[Dict[str, Any]]


@dataclass
class RuntimeContext:
    """Runtime metadata/context provided to tool implementations."""

    run_id: str
    step_id: str
    state: Dict[str, Any]
    logger: Any


class Tool(Protocol):
    """Protocol that runtime-compatible tools must implement."""

    name: str
    description: str
    input_schema: Dict[str, Any]
    timeout: Optional[float]
    retries: Optional[int]

    async def execute(self, input: Dict[str, Any], context: RuntimeContext) -> ToolResult:
        """Execute tool asynchronously and return a `ToolResult`."""
        ...
