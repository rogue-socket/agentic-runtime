from __future__ import annotations

from typing import Any, Dict, Optional
import copy


class RuntimeState:
    def __init__(self, data: Optional[Dict[str, Any]] = None, enforce_structure: bool = True) -> None:
        self._data: Dict[str, Any] = copy.deepcopy(data) if data is not None else {}
        self._meta: Dict[str, Dict[str, Any]] = {}
        if enforce_structure:
            self._data.setdefault("inputs", {})
            self._data.setdefault("steps", {})
            self._data.setdefault("runtime", {})

    def _split(self, key: str) -> list[str]:
        return [p for p in key.split(".") if p]

    def _resolve_parent(self, key: str, create: bool = False) -> tuple[Dict[str, Any], str]:
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
        try:
            parent, leaf = self._resolve_parent(key, create=False)
            return parent.get(leaf, default)
        except KeyError:
            return default

    def set(self, key: str, value: Any, step_name: Optional[str] = None) -> None:
        parent, leaf = self._resolve_parent(key, create=True)
        if leaf in parent and parent[leaf] != value:
            writer = step_name or "unknown"
            print(f"STATE WARNING: key '{key}' overwritten by step '{writer}'")
        parent[leaf] = value
        if step_name is not None:
            self._meta[key] = {"written_by": step_name}

    def exists(self, key: str) -> bool:
        marker = object()
        return self.get(key, marker) is not marker

    def delete(self, key: str) -> None:
        parent, leaf = self._resolve_parent(key, create=False)
        if leaf in parent:
            del parent[leaf]

    def snapshot(self) -> Dict[str, Any]:
        return copy.deepcopy(self._data)

    def to_dict(self) -> Dict[str, Any]:
        return copy.deepcopy(self._data)

    def set_step_output(self, step_name: str, output: Dict[str, Any], writer: Optional[str] = None) -> None:
        self.set(f"steps.{step_name}", output, step_name=writer or step_name)

    @staticmethod
    def diff(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, list[str]]:
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
        changes: list[Dict[str, Any]] = []

        def walk(b: Any, a: Any, prefix: str) -> None:
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
        value = self.get(key)
        if value is None and not self.exists(key):
            raise KeyError(key)
        return value

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(key, value)

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and self.exists(key)
