from __future__ import annotations

"""File: src/agent_runtime/memory/semantic.py

Purpose:
Provide a basic semantic-memory placeholder implementation.

Description:
Persists the latest written payload in memory without embedding/vector
logic so runtime flows remain deterministic in local tests.
"""

from typing import Any, Dict


class SemanticMemory:
    """In-memory semantic memory scaffold."""

    def __init__(self) -> None:
        """Initialize empty semantic store."""
        self._store: Dict[str, Any] = {}

    def read(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Return semantic memory snapshot copy."""
        return dict(self._store)

    def write(self, payload: Dict[str, Any]) -> None:
        """Replace semantic memory store with payload copy."""
        self._store = dict(payload)
