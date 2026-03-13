from __future__ import annotations

from typing import Any, Dict


class EpisodicMemory:
    # TODO: Implement persistent episodic memory.
    #   Should store per-run interaction history (inputs, outputs, errors) and allow
    #   retrieval of past runs by workflow_id, time range, or similarity.
    #   Consider backing with SQLite or a vector store for semantic lookup.
    def __init__(self) -> None:
        self._latest: Dict[str, Any] = {}

    def read(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return dict(self._latest)

    def write(self, payload: Dict[str, Any]) -> None:
        self._latest = dict(payload)
