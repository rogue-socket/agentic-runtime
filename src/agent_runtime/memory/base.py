from __future__ import annotations

from typing import Any, Dict, Protocol


class MemoryTier(Protocol):
    def read(self, context: Dict[str, Any]) -> Dict[str, Any]:
        ...

    def write(self, payload: Dict[str, Any]) -> None:
        ...


class MemoryManager:
    def __init__(
        self,
        working: MemoryTier,
        episodic: MemoryTier,
        semantic: MemoryTier,
        procedural: MemoryTier,
    ) -> None:
        self.working = working
        self.episodic = episodic
        self.semantic = semantic
        self.procedural = procedural

    def hydrate_state(self, state: Dict[str, Any]) -> None:
        state.update(self.working.read(state))
        state.update(self.episodic.read(state))
        state.update(self.semantic.read(state))
        state.update(self.procedural.read(state))

    def persist_state(self, state: Dict[str, Any]) -> None:
        self.working.write(state)
        self.episodic.write(state)
        self.semantic.write(state)
        self.procedural.write(state)
