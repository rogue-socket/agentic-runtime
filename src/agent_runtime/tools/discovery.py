from __future__ import annotations

"""File: src/agent_runtime/tools/discovery.py

Purpose:
Define tool discovery abstractions and placeholder implementation.

Description:
Discovery is currently scaffolded to return no dynamic tools; this file
establishes data structures for future provider-backed discovery.
"""

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class ToolSpec:
    """Metadata describing a discoverable tool."""

    name: str
    description: str
    input_schema: Dict[str, Any]


class ToolDiscovery:
    """Placeholder dynamic tool discovery service."""

    def discover(self, context: Dict[str, Any]) -> List[ToolSpec]:
        """Return discovered tool specs for a runtime context.

        Example:
            >>> ToolDiscovery().discover({})
            []
        """
        # [SCAFFOLD:TOOL_DISCOVERY] Wire to dynamic discovery backends.
        return []
