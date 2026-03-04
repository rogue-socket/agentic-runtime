from __future__ import annotations

from typing import Any, Dict


class WorkingMemory:
    def __init__(self) -> None:
        self._buffer: Dict[str, Any] = {}

    def read(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return dict(self._buffer)

    def write(self, payload: Dict[str, Any]) -> None:
        self._buffer = dict(payload)
