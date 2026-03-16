from __future__ import annotations

"""File: src/agent_runtime/utils.py

Purpose:
Provide shared utility helpers for time, hashing, state path resolution,
input materialization, and safe branch-expression evaluation.

Description:
This module supports deterministic execution internals used by workflow
loading, step execution, replay verification, and branch routing.

Key Components:
- JSON/time/hash helpers
- Dot-path state readers and step-input builder
- Restricted expression validator/evaluator for `next.when`

Dependencies:
- `datetime`, `json`, `hashlib`, `ast`

Inputs/Outputs:
- Input: runtime state dictionaries and raw text/data
- Output: normalized values used across core/workflow modules

Side Effects:
- None.
"""

from datetime import datetime, timezone
from typing import Any, Dict
import json
import hashlib
import ast


StateDict = Dict[str, Any]


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp.

    Runtime metadata uses this helper to keep a consistent timestamp
    source across run, step, and state-version persistence code paths.

    Example:
        >>> ts = utc_now()
        >>> ts.tzinfo is not None
        True
    """
    return datetime.now(timezone.utc)


def json_dumps(data: Any) -> str:
    """Serialize data to deterministic JSON string form.

    Keys are sorted to make serialized values stable for storage and
    hashing workflows where order-dependent output is undesirable.

    Example:
        >>> json_dumps({"b": 1, "a": 2})
        '{"a": 2, "b": 1}'
    """
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def json_loads(raw: str) -> Any:
    """Deserialize a JSON string into native Python objects.

    This helper mirrors `json_dumps` usage in storage modules and keeps
    serialization entry points centralized for easier future extension.

    Example:
        >>> json_loads('{"a": 1}')["a"]
        1
    """
    return json.loads(raw)


def format_template(value: Any, state: Dict[str, Any]) -> Any:
    """Recursively apply `str.format` to templated values.

    Strings are formatted with the provided state mapping; dict/list
    values are traversed recursively, while non-collection values pass
    through unchanged.

    Example:
        >>> format_template("Issue: {issue}", {"issue": "x"})
        'Issue: x'
    """
    if isinstance(value, str):
        return value.format(**state)
    if isinstance(value, dict):
        return {k: format_template(v, state) for k, v in value.items()}
    if isinstance(value, list):
        return [format_template(v, state) for v in value]
    return value


def resolve_path(path: str, state: Dict[str, Any]) -> Any:
    """Resolve dot-delimited state paths like `steps.a.summary`.

    The function traverses nested dictionaries and raises `KeyError`
    when any segment is missing, which fails fast for invalid inputs.

    Example:
        >>> resolve_path("inputs.issue", {"inputs": {"issue": "x"}})
        'x'
    """
    parts = path.split(".")
    current: Any = state
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise KeyError(f"Path not found: {path}")
    return current


def build_step_input(input_spec: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    """Materialize a step input payload from mapping specs.

    Values beginning with `inputs.` or `steps.` are resolved as state
    references; all other values are copied as literals.

    Example:
        >>> spec = {"issue": "inputs.issue", "limit": 3}
        >>> build_step_input(spec, {"inputs": {"issue": "x"}})["limit"]
        3
    """
    resolved: Dict[str, Any] = {}
    for key, value in input_spec.items():
        if isinstance(value, str) and (value.startswith("inputs.") or value.startswith("steps.")):
            resolved[key] = resolve_path(value, state)
        else:
            resolved[key] = value
    return resolved


class _DotDict:
    """Attribute-style wrapper for nested dictionaries.

    Branch expressions use this wrapper to support syntax like
    `state.inputs.issue` while preserving dictionary-backed storage.

    Example:
        >>> d = _DotDict({"a": {"b": 1}})
        >>> d.a.b
        1
    """

    def __init__(self, data: Any) -> None:
        """Store wrapped data for attribute/index access.

        Args:
            data: Any value, typically a nested dictionary.

        Example:
            >>> _DotDict({"x": 1}).to_dict()["x"]
            1
        """
        self._data = data

    def __getattr__(self, item: str) -> Any:
        """Return dictionary entries via attribute access.

        Raises:
            AttributeError: If the attribute does not exist.

        Example:
            >>> _DotDict({"x": 1}).x
            1
        """
        if isinstance(self._data, dict) and item in self._data:
            value = self._data[item]
            return _DotDict(value) if isinstance(value, dict) else value
        raise AttributeError(item)

    def __getitem__(self, item: str) -> Any:
        """Return dictionary entries via index access.

        Raises:
            KeyError: If key is not present on wrapped dictionary.

        Example:
            >>> _DotDict({"x": 1})["x"]
            1
        """
        if isinstance(self._data, dict) and item in self._data:
            value = self._data[item]
            return _DotDict(value) if isinstance(value, dict) else value
        raise KeyError(item)

    def to_dict(self) -> Any:
        """Return the original wrapped object.

        Example:
            >>> _DotDict({"x": 1}).to_dict()
            {'x': 1}
        """
        return self._data


class _SafeExprValidator(ast.NodeVisitor):
    """AST validator for restricted branch condition expressions.

    Only a narrow subset of nodes and names are accepted so expression
    evaluation remains deterministic and lower risk than raw `eval`.
    """

    allowed_names = {"state", "len"}

    def visit(self, node: ast.AST) -> None:
        """Allow only approved AST node types.

        Raises:
            ValueError: If expression includes unsupported nodes.

        Example:
            >>> _SafeExprValidator().visit(ast.parse("len(state.inputs)", mode="eval"))
        """
        if isinstance(node, (ast.Expression, ast.BoolOp, ast.Compare, ast.Name, ast.Load, ast.Attribute,
                             ast.Constant, ast.UnaryOp, ast.BinOp, ast.And, ast.Or, ast.Eq, ast.NotEq,
                             ast.Gt, ast.GtE, ast.Lt, ast.LtE)):
            return super().visit(node)
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "len" and len(node.args) == 1:
                return super().visit(node)
        raise ValueError("Unsupported expression")

    def visit_Name(self, node: ast.Name) -> None:
        """Validate that only whitelisted symbol names are used.

        Raises:
            ValueError: If a non-whitelisted name appears.

        Example:
            >>> _SafeExprValidator().visit(ast.parse("state.inputs", mode="eval"))
        """
        if node.id not in self.allowed_names:
            raise ValueError("Unsupported name")
        return super().visit_Name(node)


def safe_eval(expr: str, state: Dict[str, Any]) -> bool:
    """Evaluate a validated branch condition expression safely.

    The expression is parsed/validated with `_SafeExprValidator`, then
    executed with a restricted globals scope and `state` dot wrapper.

    Example:
        >>> safe_eval("state.inputs.issue == 'bug'", {"inputs": {"issue": "bug"}})
        True
    """
    # [SCAFFOLD:DETERMINISM] Simple safe eval; replace with dedicated expression engine later.
    tree = ast.parse(expr, mode="eval")
    _SafeExprValidator().visit(tree)
    context = {"state": _DotDict(state), "len": len}
    return bool(eval(compile(tree, "<expr>", "eval"), {"__builtins__": {}}, context))


def sha256_text(text: str) -> str:
    """Return SHA-256 hash for a text payload.

    Example:
        >>> len(sha256_text("abc"))
        64
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_json(data: Any) -> str:
    """Return SHA-256 hash of canonicalized JSON data.

    Canonicalization sorts keys and strips whitespace so semantically
    equivalent objects produce the same hash.

    Example:
        >>> sha256_json({"b": 1, "a": 2}) == sha256_json({"a": 2, "b": 1})
        True
    """
    # [SCAFFOLD:DETERMINISM] Canonical JSON hash; migrate to full event sourcing later.
    canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_text(canonical)
