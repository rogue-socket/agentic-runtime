from __future__ import annotations

from typing import Any, Dict


class SemanticMemory:
    def __init__(self) -> None:
        self._store: Dict[str, Any] = {}

    def read(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return dict(self._store)

    def write(self, payload: Dict[str, Any]) -> None:
        self._store = dict(payload)
