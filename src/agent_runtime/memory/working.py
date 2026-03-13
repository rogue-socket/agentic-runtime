from __future__ import annotations

from typing import Any, Dict


class WorkingMemory:
    # TODO: Implement scoped working memory.
    #   Should manage active execution context (current task, recent messages, scratch
    #   state) with automatic compression/summarization when context grows too large.
    def __init__(self) -> None:
        self._buffer: Dict[str, Any] = {}

    def read(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return dict(self._buffer)

    def write(self, payload: Dict[str, Any]) -> None:
        self._buffer = dict(payload)
