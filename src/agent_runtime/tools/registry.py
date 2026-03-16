from __future__ import annotations

"""File: src/agent_runtime/tools/registry.py

Purpose:
Maintain runtime-accessible mapping of tool name to tool object.

Description:
Executor resolves `tool:` references through this registry at runtime;
missing entries are surfaced as typed errors.
"""

from typing import Dict

from ..errors import ToolNotFoundError
from .base import Tool


class ToolRegistry:
    """In-memory registry for runtime tool implementations."""

    def __init__(self) -> None:
        """Initialize empty tool map."""
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register or replace tool by its declared name."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        """Return tool by name or raise `ToolNotFoundError`."""
        if name not in self._tools:
            raise ToolNotFoundError(f"Tool not found: {name}")
        return self._tools[name]
