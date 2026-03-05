from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict
import json
import hashlib
import ast


StateDict = Dict[str, Any]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def json_loads(raw: str) -> Any:
    return json.loads(raw)


def format_template(value: Any, state: Dict[str, Any]) -> Any:
    if isinstance(value, str):
        return value.format(**state)
    if isinstance(value, dict):
        return {k: format_template(v, state) for k, v in value.items()}
    if isinstance(value, list):
        return [format_template(v, state) for v in value]
    return value


def resolve_path(path: str, state: Dict[str, Any]) -> Any:
    parts = path.split(".")
    current: Any = state
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise KeyError(f"Path not found: {path}")
    return current


def build_step_input(input_spec: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    resolved: Dict[str, Any] = {}
    for key, value in input_spec.items():
        if isinstance(value, str) and (value.startswith("inputs.") or value.startswith("steps.")):
            resolved[key] = resolve_path(value, state)
        else:
            resolved[key] = value
    return resolved


class _DotDict:
    def __init__(self, data: Any) -> None:
        self._data = data

    def __getattr__(self, item: str) -> Any:
        if isinstance(self._data, dict) and item in self._data:
            value = self._data[item]
            return _DotDict(value) if isinstance(value, dict) else value
        raise AttributeError(item)

    def __getitem__(self, item: str) -> Any:
        if isinstance(self._data, dict) and item in self._data:
            value = self._data[item]
            return _DotDict(value) if isinstance(value, dict) else value
        raise KeyError(item)

    def to_dict(self) -> Any:
        return self._data


class _SafeExprValidator(ast.NodeVisitor):
    allowed_names = {"state", "len"}

    def visit(self, node: ast.AST) -> None:
        if isinstance(node, (ast.Expression, ast.BoolOp, ast.Compare, ast.Name, ast.Load, ast.Attribute,
                             ast.Constant, ast.UnaryOp, ast.BinOp, ast.And, ast.Or, ast.Eq, ast.NotEq,
                             ast.Gt, ast.GtE, ast.Lt, ast.LtE)):
            return super().visit(node)
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "len" and len(node.args) == 1:
                return super().visit(node)
        raise ValueError("Unsupported expression")

    def visit_Name(self, node: ast.Name) -> None:
        if node.id not in self.allowed_names:
            raise ValueError("Unsupported name")
        return super().visit_Name(node)


def safe_eval(expr: str, state: Dict[str, Any]) -> bool:
    # [SCAFFOLD:DETERMINISM] Simple safe eval; replace with dedicated expression engine later.
    tree = ast.parse(expr, mode="eval")
    _SafeExprValidator().visit(tree)
    context = {"state": _DotDict(state), "len": len}
    return bool(eval(compile(tree, "<expr>", "eval"), {"__builtins__": {}}, context))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_json(data: Any) -> str:
    # [SCAFFOLD:DETERMINISM] Canonical JSON hash; migrate to full event sourcing later.
    canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_text(canonical)
