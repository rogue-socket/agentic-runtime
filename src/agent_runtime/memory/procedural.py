from __future__ import annotations

"""File: src/agent_runtime/memory/procedural.py

Purpose:
Provide a minimal procedural-memory placeholder implementation.

Description:
Stores latest payload only; intended as scaffold until action-policy
retrieval and behavior-rule storage are implemented.
"""

from typing import Any, Dict


class ProceduralMemory:
    """In-memory procedural memory scaffold."""

    def __init__(self) -> None:
        """Initialize empty procedural memory store."""
        self._store: Dict[str, Any] = {}

    def read(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Return current procedural memory snapshot."""
        return dict(self._store)

    def write(self, payload: Dict[str, Any]) -> None:
        """Replace procedural memory with latest payload."""
        self._store = dict(payload)
