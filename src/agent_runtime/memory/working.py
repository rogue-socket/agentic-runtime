from __future__ import annotations

"""File: src/agent_runtime/memory/working.py

Purpose:
Provide a simple in-memory working-memory tier.

Description:
Stores the latest payload in a process-local buffer and returns a copy
on reads for mutation safety in callers.
"""

from typing import Any, Dict


class WorkingMemory:
    # TODO: Implement scoped working memory.
    #   Should manage active execution context (current task, recent messages, scratch
    #   state) with automatic compression/summarization when context grows too large.
    # NOTE: This is lower priority than episodic memory. Ship episodic (SQLite-backed,
    #   already implemented) as the first production-ready tier before investing here.
    def __init__(self) -> None:
        """Initialize empty working-memory buffer."""
        self._buffer: Dict[str, Any] = {}

    def read(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Return latest working-memory snapshot copy."""
        return dict(self._buffer)

    def write(self, payload: Dict[str, Any]) -> None:
        """Replace working-memory buffer with latest payload copy."""
        self._buffer = dict(payload)
