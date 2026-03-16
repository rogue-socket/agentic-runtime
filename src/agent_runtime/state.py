from __future__ import annotations

"""File: src/agent_runtime/state.py

Purpose:
Encapsulate runtime state access, mutation, snapshots, and diffs.

Description:
`RuntimeState` provides namespaced key operations (`inputs`, `steps`,
`runtime`) and utilities for shallow/deep state change inspection.

Key Components:
- `RuntimeState` key-path API and diff helpers

Dependencies:
- `copy` plus standard typing primitives

Inputs/Outputs:
- Input: nested state dictionaries and dot-path keys
- Output: validated state reads/writes and diff descriptors

Side Effects:
- Prints overwrite warning when existing keys are changed.
"""

from typing import Any, Dict, Optional
import copy


class RuntimeState:
    """Mutable runtime state wrapper with dot-path helpers.

    The class standardizes state shape and key traversal so execution,
    replay, and CLI inspection use one consistent state contract.

    Example:
        >>> s = RuntimeState({"inputs": {"issue": "x"}, "steps": {}, "runtime": {}})
        >>> s.get("inputs.issue")
        'x'
    """

    def __init__(self, data: Optional[Dict[str, Any]] = None, enforce_structure: bool = True) -> None:
        """Initialize runtime state with optional structure enforcement.

        Args:
            data: Initial nested state dictionary.
            enforce_structure: Ensure `inputs/steps/runtime` namespaces exist.

        Example:
            >>> RuntimeState({}, enforce_structure=True).to_dict()["steps"]
            {}
        """
        self._data: Dict[str, Any] = copy.deepcopy(data) if data is not None else {}
        self._meta: Dict[str, Dict[str, Any]] = {}
        if enforce_structure:
            self._data.setdefault("inputs", {})
            self._data.setdefault("steps", {})
            self._data.setdefault("runtime", {})

    def _split(self, key: str) -> list[str]:
        """Split dotted key paths into non-empty segments.

        Example:
            >>> RuntimeState({})._split("a.b")
            ['a', 'b']
        """
        return [p for p in key.split(".") if p]

    def _resolve_parent(self, key: str, create: bool = False) -> tuple[Dict[str, Any], str]:
        """Resolve parent mapping and leaf key for a dotted path.

        Args:
            key: Dotted key like `steps.s1.summary`.
            create: Create missing intermediate dicts when True.

        Example:
            >>> RuntimeState({})._resolve_parent("runtime.flag", create=True)[1]
            'flag'
        """
        parts = self._split(key)
        if not parts:
            raise ValueError("key must not be empty")
        node: Dict[str, Any] = self._data
        for part in parts[:-1]:
            if part not in node:
                if not create:
                    raise KeyError(key)
                node[part] = {}
            child = node[part]
            if not isinstance(child, dict):
                if not create:
                    raise KeyError(key)
                node[part] = {}
                child = node[part]
            node = child
        return node, parts[-1]

    def get(self, key: str, default: Any = None) -> Any:
        """Read a value by dotted key path.

        Returns `default` if path is missing, matching dict-like behavior
        while preserving the nested structure abstraction.

        Example:
            >>> RuntimeState({"runtime": {"x": 1}}).get("runtime.x")
            1
        """
        try:
            parent, leaf = self._resolve_parent(key, create=False)
            return parent.get(leaf, default)
        except KeyError:
            return default

    def set(self, key: str, value: Any, step_name: Optional[str] = None) -> None:
        """Write a value by dotted key path.

        Overwrites are allowed but emit a warning to highlight potential
        ownership conflicts between steps.

        Example:
            >>> s = RuntimeState({"runtime": {}})
            >>> s.set("runtime.mode", "test")
        """
        parent, leaf = self._resolve_parent(key, create=True)
        if leaf in parent and parent[leaf] != value:
            writer = step_name or "unknown"
            print(f"STATE WARNING: key '{key}' overwritten by step '{writer}'")
        parent[leaf] = value
        if step_name is not None:
            self._meta[key] = {"written_by": step_name}

    def exists(self, key: str) -> bool:
        """Return True when dotted key path exists.

        Example:
            >>> RuntimeState({"runtime": {"x": 1}}).exists("runtime.x")
            True
        """
        marker = object()
        return self.get(key, marker) is not marker

    def delete(self, key: str) -> None:
        """Delete a dotted key path when present.

        Example:
            >>> s = RuntimeState({"runtime": {"x": 1}})
            >>> s.delete("runtime.x")
        """
        parent, leaf = self._resolve_parent(key, create=False)
        if leaf in parent:
            del parent[leaf]

    def snapshot(self) -> Dict[str, Any]:
        """Return deep copy snapshot for safe mutation/testing.

        Example:
            >>> isinstance(RuntimeState({}).snapshot(), dict)
            True
        """
        return copy.deepcopy(self._data)

    def to_dict(self) -> Dict[str, Any]:
        """Return deep copy of current state payload.

        Example:
            >>> RuntimeState({"inputs": {}}).to_dict()["inputs"] == {}
            True
        """
        return copy.deepcopy(self._data)

    def set_step_output(self, step_name: str, output: Dict[str, Any], writer: Optional[str] = None) -> None:
        """Write a step output under `steps.<step_name>`.

        Example:
            >>> s = RuntimeState({"steps": {}, "inputs": {}, "runtime": {}})
            >>> s.set_step_output("a", {"ok": True})
        """
        self.set(f"steps.{step_name}", output, step_name=writer or step_name)

    @staticmethod
    def diff(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, list[str]]:
        """Compute top-level add/remove/change keys.

        This summary diff is used by CLI state-history text output where
        high-level change hints are sufficient.

        Example:
            >>> RuntimeState.diff({"a": 1}, {"a": 2})["changed"]
            ['a']
        """
        added: list[str] = []
        removed: list[str] = []
        changed: list[str] = []
        for key in before:
            if key not in after:
                removed.append(key)
            elif before[key] != after[key]:
                changed.append(key)
        for key in after:
            if key not in before:
                added.append(key)
        return {"added": added, "removed": removed, "changed": changed}

    @staticmethod
    def diff_paths(before: Dict[str, Any], after: Dict[str, Any]) -> list[Dict[str, Any]]:
        """Compute recursive path-level diffs for nested dictionaries.

        Returns operation entries using `+` (added), `-` (removed), and
        `~` (changed) for visualization and detailed state inspection.

        Example:
            >>> RuntimeState.diff_paths({"a": {}}, {"a": {"b": 1}})[0]["op"]
            '+'
        """
        changes: list[Dict[str, Any]] = []

        def walk(b: Any, a: Any, prefix: str) -> None:
            """Auto-generated documentation for this callable.
            
            Describes purpose, expected inputs/outputs, and behavior in this module.
            
            Example:
                >>> # Example 1
                >>> walk
                >>> # Example 2
                >>> walk
            """
            if isinstance(b, dict) and isinstance(a, dict):
                b_keys = set(b.keys())
                a_keys = set(a.keys())
                for key in sorted(b_keys - a_keys):
                    path = f"{prefix}.{key}" if prefix else key
                    changes.append({"op": "-", "path": path, "before": b[key], "after": None})
                for key in sorted(a_keys - b_keys):
                    path = f"{prefix}.{key}" if prefix else key
                    changes.append({"op": "+", "path": path, "before": None, "after": a[key]})
                for key in sorted(a_keys & b_keys):
                    path = f"{prefix}.{key}" if prefix else key
                    walk(b[key], a[key], path)
                return
            if b != a:
                changes.append({"op": "~", "path": prefix, "before": b, "after": a})

        walk(before, after, "")
        return changes

    def __getitem__(self, key: str) -> Any:
        """Dictionary-style access wrapper around `get`.

        Raises `KeyError` when value is missing to align with mapping
        semantics used by handlers in tests and runtime code.
        """
        value = self.get(key)
        if value is None and not self.exists(key):
            raise KeyError(key)
        return value

    def __setitem__(self, key: str, value: Any) -> None:
        """Dictionary-style setter wrapper.

        Example:
            >>> s = RuntimeState({"runtime": {}})
            >>> s["runtime.flag"] = True
        """
        self.set(key, value)

    def __contains__(self, key: object) -> bool:
        """Return True if string key path exists in state."""
        return isinstance(key, str) and self.exists(key)
