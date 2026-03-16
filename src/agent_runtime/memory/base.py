from __future__ import annotations

"""File: src/agent_runtime/memory/base.py

Purpose:
Define memory tier protocol and coordinator used by the executor.

Description:
`MemoryManager` orchestrates hydration/persistence across working,
episodic, semantic, and procedural memory tiers.

Key Components:
- `MemoryTier` protocol
- `MemoryManager`

Dependencies:
- Standard typing only

Inputs/Outputs:
- Input: state/context dictionaries
- Output: merged hydrated state and persisted tier writes

Side Effects:
- Calls into memory tier backends, which may store data.
"""

from typing import Any, Dict, Protocol


class MemoryTier(Protocol):
    """Protocol implemented by memory tiers.

    Example:
        >>> hasattr(MemoryTier, "read")
        True
    """
    def read(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Auto-generated documentation for this callable.
        
        Describes purpose, expected inputs/outputs, and behavior in this module.
        
        Example:
            >>> # Example 1
            >>> read
            >>> # Example 2
            >>> read
        """
        ...

    def write(self, payload: Dict[str, Any]) -> None:
        """Auto-generated documentation for this callable.
        
        Describes purpose, expected inputs/outputs, and behavior in this module.
        
        Example:
            >>> # Example 1
            >>> write
            >>> # Example 2
            >>> write
        """
        ...


class MemoryManager:
    """Coordinate reads/writes across all memory tiers.

    Executor uses this class before and after each step so transient and
    persistent memories can contribute to run state evolution.
    """

    def __init__(
        self,
        working: MemoryTier,
        episodic: MemoryTier,
        semantic: MemoryTier,
        procedural: MemoryTier,
    ) -> None:
        """Store concrete memory tier instances."""
        self.working = working
        self.episodic = episodic
        self.semantic = semantic
        self.procedural = procedural

    def hydrate_state(self, state: Dict[str, Any]) -> None:
        """Merge memory snapshots into mutable runtime state.

        # TODO: BUG
        # This `dict.update` strategy can overwrite top-level namespaces
        # (e.g., `inputs`, `steps`) and corrupt run-local state ownership.
        # Suggested fix: merge under dedicated namespaces or deep-merge only
        # allowed keys instead of blind top-level updates.
        """
        state.update(self.working.read(state))
        state.update(self.episodic.read(state))
        state.update(self.semantic.read(state))
        state.update(self.procedural.read(state))

    def persist_state(self, state: Dict[str, Any]) -> None:
        """Persist current state into each memory tier.

        Example:
            >>> # Called by executor after step output commit.
            >>> True
            True
        """
        self.working.write(state)
        self.episodic.write(state)
        self.semantic.write(state)
        self.procedural.write(state)
