from __future__ import annotations

from typing import Any, Dict


class ProceduralMemory:
    # TODO: Implement persistent procedural memory.
    #   Should store learned workflows, playbooks, and reusable strategies that the
    #   runtime can recall when executing similar tasks in the future.
    def __init__(self) -> None:
        self._store: Dict[str, Any] = {}

    def read(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return dict(self._store)

    def write(self, payload: Dict[str, Any]) -> None:
        self._store = dict(payload)
