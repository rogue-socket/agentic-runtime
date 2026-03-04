from __future__ import annotations

from typing import Any, Dict


class EpisodicMemory:
    def __init__(self) -> None:
        self._latest: Dict[str, Any] = {}

    def read(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return dict(self._latest)

    def write(self, payload: Dict[str, Any]) -> None:
        self._latest = dict(payload)
