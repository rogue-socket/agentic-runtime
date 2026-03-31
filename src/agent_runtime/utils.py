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
import re
import string


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
    """Recursively substitute ``$key`` / ``${key}`` placeholders in templated values.

    Uses :class:`string.Template` with ``safe_substitute`` so that
    missing keys are left as-is rather than raising ``KeyError``, and
    Python format-string mini-language attacks (``{0.__class__}``) are
    not possible.

    Example:
        >>> format_template("Issue: $issue", {"issue": "x"})
        'Issue: x'
    """
    if isinstance(value, str):
        return string.Template(value).safe_substitute(state)
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


_PATH_TEMPLATE_RE = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")


def _sanitize_interpolated_value(value: Any) -> str:
    """Normalize interpolated template values to safer prompt text.

    - Strings: strip NUL bytes and non-printable control chars.
    - Dict/list: serialize to stable JSON instead of Python repr.
    - Everything else: ``str(value)``.
    """
    if isinstance(value, str):
        value = value.replace("\x00", "")
        return "".join(ch for ch in value if ch in "\n\r\t" or ord(ch) >= 0x20)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def render_path_template(text: str, state: Dict[str, Any]) -> str:
    """Render ``{{ path }}`` placeholders using dot-path lookups.

    Example:
        >>> render_path_template("Issue: {{ inputs.issue }}", {"inputs": {"issue": "x"}})
        'Issue: x'
    """
    def replace(match: re.Match[str]) -> str:
        path = match.group(1).strip()
        return _sanitize_interpolated_value(resolve_path(path, state))

    return _PATH_TEMPLATE_RE.sub(replace, text)


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

    def __len__(self) -> int:
        """Return length of wrapped data (dict, list, or string)."""
        if isinstance(self._data, (dict, list, str)):
            return len(self._data)
        raise TypeError(f"object of type '{type(self._data).__name__}' has no len()")

    def __bool__(self) -> bool:
        """Return truthiness of wrapped data."""
        return bool(self._data)

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


class _SafeExprValidator(ast.NodeVisitor):
    """AST validator for restricted branch condition expressions.

    Only a narrow subset of nodes and names are accepted so expression
    evaluation remains deterministic and lower risk than raw `eval`.
    """

    allowed_names = {"state", "len", "min", "max", "abs"}
    allowed_string_methods = {
        "startswith": (1, 2),
        "endswith": (1, 2),
        "lower": (0, 0),
        "upper": (0, 0),
        "strip": (0, 1),
    }

    def visit(self, node: ast.AST) -> None:
        """Allow only approved AST node types.

        Raises:
            ValueError: If expression includes unsupported nodes.

        Example:
            >>> _SafeExprValidator().visit(ast.parse("len(state.inputs)", mode="eval"))
        """
        if isinstance(node, (ast.Expression, ast.BoolOp, ast.Compare, ast.Name, ast.Load, ast.Attribute,
                             ast.Constant, ast.UnaryOp, ast.BinOp, ast.And, ast.Or, ast.Eq, ast.NotEq,
                             ast.Gt, ast.GtE, ast.Lt, ast.LtE, ast.In, ast.NotIn,
                             ast.List, ast.Tuple, ast.Set,
                             ast.Not, ast.USub, ast.UAdd, ast.Invert,
                             ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod)):
            return super().visit(node)
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "len" and len(node.args) == 1 and not node.keywords:
                return super().visit(node)
            if isinstance(node.func, ast.Name) and node.func.id in {"min", "max"} and len(node.args) >= 1 and not node.keywords:
                return super().visit(node)
            if isinstance(node.func, ast.Name) and node.func.id == "abs" and len(node.args) == 1 and not node.keywords:
                return super().visit(node)
            if isinstance(node.func, ast.Attribute) and not node.keywords:
                method_name = node.func.attr
                bounds = self.allowed_string_methods.get(method_name)
                if bounds is not None:
                    min_args, max_args = bounds
                    if min_args <= len(node.args) <= max_args:
                        return super().visit(node)
            raise ValueError("Unsupported expression")
        if isinstance(node, ast.keyword):
            # Keep expression surface predictable and compact.
            raise ValueError("Unsupported expression")
        if isinstance(node, (ast.Subscript, ast.Slice)):
            # Bracket indexing and slicing add complexity and are not required
            # for supported branch-condition patterns.
            raise ValueError("Unsupported expression")
        if isinstance(node, (ast.Dict, ast.DictComp, ast.ListComp, ast.SetComp, ast.GeneratorExp)):
            raise ValueError("Unsupported expression")
        raise ValueError("Unsupported expression")

    def visit_Call(self, node: ast.Call) -> None:
        """Validate function and method calls in expressions.

        Only a bounded allowlist is supported, enforced in :meth:`visit`.
        This visitor adds semantic checks for method-call receivers.
        """
        if isinstance(node.func, ast.Attribute):
            method_name = node.func.attr
            if method_name in self.allowed_string_methods:
                receiver = node.func.value
                if isinstance(receiver, ast.Attribute):
                    return self.generic_visit(node)
                if isinstance(receiver, ast.Call):
                    if isinstance(receiver.func, ast.Attribute) and receiver.func.attr in self.allowed_string_methods:
                        return self.generic_visit(node)
                if isinstance(receiver, ast.Constant) and isinstance(receiver.value, str):
                    return self.generic_visit(node)
                raise ValueError("Unsupported expression")
        return self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """Block access to private/dunder attributes for safety."""
        if node.attr.startswith("_"):
            raise ValueError(f"Access to private attribute '{node.attr}' is not allowed")
        return self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        """Validate that only whitelisted symbol names are used.

        Raises:
            ValueError: If a non-whitelisted name appears.

        Example:
            >>> _SafeExprValidator().visit(ast.parse("state.inputs", mode="eval"))
        """
        if node.id not in self.allowed_names:
            raise ValueError("Unsupported name")
        return self.generic_visit(node)


def safe_eval(expr: str, state: Dict[str, Any]) -> bool:
    """Evaluate a validated branch condition expression safely.

    The expression is parsed/validated with `_SafeExprValidator`, then
    executed with a restricted globals scope and `state` dot wrapper.

    Example:
        >>> safe_eval("state.inputs.issue == 'bug'", {"inputs": {"issue": "bug"}})
        True
    """
    # [SCAFFOLD:DETERMINISM] Simple safe eval; replace with dedicated expression engine later.
    # TODO(eng): expression-language - Expand the expression language for
    #   branch conditions.  Currently limited to `state` and `len`.
    #   Useful additions:
    #   - String methods: .startswith(), .endswith(), .lower(), "x" in state.y
    #   - Math helpers: min, max, abs
    #   - Membership tests: value in [list]
    #   - Regex matching: re_match(pattern, state.field)
    #   Must preserve determinism and block unsafe execution.
    #   Consider replacing the AST-walk approach with a small grammar
    #   (e.g., Lark or a hand-rolled recursive-descent parser) so the
    #   language surface is explicit rather than an implicit subset of Python.
    tree = ast.parse(expr, mode="eval")
    _SafeExprValidator().visit(tree)
    context = {"state": _DotDict(state), "len": len, "min": min, "max": max, "abs": abs}
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


def version_sort_key(v: str):
    """Sort key that handles versions like `v1`, `v1.1`, and `v10` correctly."""
    from .schema_versioning import version_components

    try:
        return (0, version_components(v))
    except ValueError:
        return (1, v)
