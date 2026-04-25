from __future__ import annotations

"""File: src/agent_runtime/memory/base.py

Purpose:
Define memory tier protocol and coordinator used by the executor.

Description:
`MemoryManager` orchestrates hydration/persistence across working,
episodic, semantic, and procedural memory tiers.  Each tier writes
exclusively to its own namespace under ``runtime.memory.<tier>`` to
prevent cross-tier state corruption.

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
    """Protocol implemented by memory tiers."""

    def read(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Return tier-specific data to merge into state."""
        ...

    def write(self, payload: Dict[str, Any]) -> None:
        """Persist relevant data from current state."""
        ...


def _deep_merge(target: Dict[str, Any], source: Dict[str, Any]) -> None:
    """Recursively merge *source* into *target* in place.

    Dict values are merged recursively; non-dict values from *source*
    overwrite *target*.
    """
    for key, value in source.items():
        if key in target and isinstance(target[key], dict) and isinstance(value, dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value


class MemoryManager:
    """Coordinate reads/writes across all memory tiers.

    Executor uses this class before and after each step so transient and
    persistent memories can contribute to run state evolution.

    Each tier's output is namespaced under ``runtime.memory.<tier>`` to
    prevent cross-tier collisions and protect the ``inputs``/``steps``
    namespaces from accidental overwrites.
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

        Each tier writes only to ``runtime.memory.<tier>`` using deep-merge,
        preserving the ``inputs`` and ``steps`` namespaces.
        """
        runtime = state.setdefault("runtime", {})
        memory_ns = runtime.setdefault("memory", {})

        for name, tier in self._tiers():
            tier_data = tier.read(state)
            if tier_data:
                tier_ns = memory_ns.setdefault(name, {})
                _deep_merge(tier_ns, tier_data)

    # TODO(pain-point): Workflow-Level Degradation Strategy - The executor
    #   supports `optional: true` per step with `default_output`, but there's
    #   no workflow-level degradation policy. Add support for: (1) a circuit
    #   breaker that tracks consecutive failures across steps and aborts early
    #   with a partial-success result, (2) a `degradation_mode` workflow
    #   setting ("best-effort" | "strict") controlling whether partial outputs
    #   are acceptable, (3) a `quality_threshold` that checks cumulative
    #   degraded-step count and fails the run if too many steps fell back to
    #   defaults. This turns single-step resilience into pipeline resilience.
    def persist_state(self, state: Dict[str, Any]) -> None:
        """Persist current state into each memory tier."""
        for _name, tier in self._tiers():
            tier.write(state)

    def _tiers(self):
        """Yield (name, tier) pairs."""
        yield "working", self.working
        yield "episodic", self.episodic
        yield "semantic", self.semantic
        yield "procedural", self.procedural

    def close(self) -> None:
        """Close all memory tiers that support it.

        Each tier is closed independently so a failure in one does not
        prevent the others from releasing resources.
        """
        errors: list[tuple[str, Exception]] = []
        for name, tier in self._tiers():
            close_fn = getattr(tier, "close", None)
            if callable(close_fn):
                try:
                    close_fn()
                except Exception as exc:  # noqa: BLE001
                    errors.append((name, exc))
        if errors:
            names = ", ".join(n for n, _ in errors)
            raise RuntimeError(f"Failed to close memory tier(s): {names}")
