from __future__ import annotations

"""File: src/agent_runtime/memory/episodic.py

Purpose:
Provide a minimal in-memory episodic-memory tier.

Description:
Maintains only the latest payload snapshot in process memory and serves
as a placeholder for future event/history-oriented memory backends.
"""

from typing import Any, Dict


class EpisodicMemory:
    # TODO: Implement persistent episodic memory.
    #   Should store per-run interaction history (inputs, outputs, errors) and allow
    #   retrieval of past runs by workflow_id, time range, or similarity.
    #   Consider backing with SQLite or a vector store for semantic lookup.
    def __init__(self) -> None:
        """Initialize empty episodic memory store."""
        self._latest: Dict[str, Any] = {}

    def read(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Return current episodic memory snapshot."""
        return dict(self._latest)

    def write(self, payload: Dict[str, Any]) -> None:
        """Replace episodic memory with latest payload."""
        self._latest = dict(payload)
