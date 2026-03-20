from __future__ import annotations

"""Run-scoped working memory tier.

Manages the active execution context for a single run: scratch key-value
state, a sliding window of recent entries (messages, observations, etc.),
and automatic eviction when the context exceeds a configurable entry limit.

Working memory is **ephemeral** — it lives only for the duration of a run
and is not persisted to disk.  Its role is to give steps a structured
scratchpad and a bounded recent-context window without polluting the
formal state tree.
"""

import copy
import json
from collections import deque
from typing import Any, Deque, Dict, List, Optional


class WorkingMemory:
    """In-process working memory scoped to a single run.

    Provides three facilities:

    1. **Scratch** — arbitrary key-value pairs steps can read/write for
       transient coordination (e.g., ``scratch["current_plan"]``).
    2. **Entries** — an ordered sliding window of context items (recent
       messages, tool outputs, observations).  Oldest entries are evicted
       automatically when ``max_entries`` is exceeded.
    3. **Active task** — a single dict describing the current objective so
       model steps can receive focused context without scanning all state.

    All data returned by ``read()`` is deep-copied to prevent callers from
    mutating the internal buffers.
    """

    def __init__(self, max_entries: int = 50, max_scratch_bytes: int = 256_000) -> None:
        """Initialize working memory with capacity limits.

        Args:
            max_entries: Maximum number of context entries retained in the
                sliding window.  When exceeded, the oldest entries are
                silently evicted.
            max_scratch_bytes: Approximate byte budget for the scratch store.
                When a ``put`` would exceed this limit, the write is rejected
                with a ``ValueError`` so callers can decide what to evict.
        """
        self._scratch: Dict[str, Any] = {}
        self._entries: Deque[Dict[str, Any]] = deque(maxlen=max_entries)
        self._active_task: Optional[Dict[str, Any]] = None
        self._max_entries = max_entries
        self._max_scratch_bytes = max_scratch_bytes

    # ------------------------------------------------------------------
    # MemoryTier protocol
    # ------------------------------------------------------------------

    def read(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Return a snapshot of working memory for state hydration.

        The returned dict is intended for merging under
        ``runtime.memory.working`` by the ``MemoryManager``.
        """
        result: Dict[str, Any] = {}
        if self._scratch:
            result["scratch"] = copy.deepcopy(self._scratch)
        if self._entries:
            result["entries"] = [copy.deepcopy(e) for e in self._entries]
        if self._active_task is not None:
            result["active_task"] = copy.deepcopy(self._active_task)
        return result

    def write(self, payload: Dict[str, Any]) -> None:
        """Persist relevant state fragments into working memory.

        Extracts the current step's output (latest key in ``steps``) and
        appends it as a context entry so subsequent steps see recent
        activity.
        """
        steps = payload.get("steps", {})
        if steps:
            # Add the most-recently-written step output as an entry.
            # TODO(Eng-6, dict-order): Relies on dict insertion order (Python 3.7+)
            #   to grab the "latest" step output.  This is fragile — if state is
            #   round-tripped through JSON or a DB, key order may not reflect
            #   execution order.  Use an explicit timestamp or sequence number
            #   embedded in the step output to identify the most recent entry.
            last_key = list(steps.keys())[-1]
            self.add_entry("step_output", {
                "step_id": last_key,
                "output": steps[last_key],
            })

    # ------------------------------------------------------------------
    # Scratch key-value API
    # ------------------------------------------------------------------

    def put(self, key: str, value: Any) -> None:
        """Store a scratch value, enforcing the byte budget.

        Raises ``ValueError`` if the write would exceed
        ``max_scratch_bytes``.
        """
        trial = {**self._scratch, key: value}
        if self._estimate_bytes(trial) > self._max_scratch_bytes:
            raise ValueError(
                f"Scratch byte budget exceeded ({self._max_scratch_bytes} bytes); "
                f"remove unused keys before writing '{key}'."
            )
        self._scratch[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Read a scratch value by key."""
        return self._scratch.get(key, default)

    def remove(self, key: str) -> None:
        """Delete a scratch key if present."""
        self._scratch.pop(key, None)

    def clear_scratch(self) -> None:
        """Remove all scratch entries."""
        self._scratch.clear()

    # ------------------------------------------------------------------
    # Context entries (sliding window)
    # ------------------------------------------------------------------

    def add_entry(self, kind: str, data: Dict[str, Any]) -> None:
        """Append a context entry; oldest entries are evicted automatically.

        Args:
            kind: Category label (e.g. ``"step_output"``, ``"observation"``).
            data: Arbitrary payload for this entry.
        """
        self._entries.append({"kind": kind, **data})

    def recent_entries(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Return the *limit* most recent entries (all if *limit* is None)."""
        entries = list(self._entries)
        if limit is not None:
            entries = entries[-limit:]
        return [copy.deepcopy(e) for e in entries]

    # ------------------------------------------------------------------
    # Active task
    # ------------------------------------------------------------------

    def set_active_task(self, task: Dict[str, Any]) -> None:
        """Set the current task objective."""
        self._active_task = copy.deepcopy(task)

    def get_active_task(self) -> Optional[Dict[str, Any]]:
        """Return the current task or None."""
        return copy.deepcopy(self._active_task) if self._active_task else None

    def clear_active_task(self) -> None:
        """Clear the active task."""
        self._active_task = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear all working memory (called at run end)."""
        self._scratch.clear()
        self._entries.clear()
        self._active_task = None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _estimate_bytes(data: Any) -> int:
        """Approximate JSON-serialized size for budget enforcement."""
        try:
            return len(json.dumps(data, default=str))
        except (TypeError, ValueError):
            return 0
