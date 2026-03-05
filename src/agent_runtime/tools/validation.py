from __future__ import annotations

from typing import Any, Dict


def validate_input(payload: Dict[str, Any], schema: Dict[str, Any]) -> None:
    if not schema:
        return
    if schema.get("type") != "object":
        raise ValueError("Only object schemas are supported.")
    properties = schema.get("properties", {})
    for key, rule in properties.items():
        if key not in payload:
            continue
        expected = rule.get("type")
        value = payload[key]
        if expected == "string" and not isinstance(value, str):
            raise ValueError(f"Field '{key}' must be string")
        if expected == "number" and not isinstance(value, (int, float)):
            raise ValueError(f"Field '{key}' must be number")
        if expected == "boolean" and not isinstance(value, bool):
            raise ValueError(f"Field '{key}' must be boolean")
        if expected == "object" and not isinstance(value, dict):
            raise ValueError(f"Field '{key}' must be object")
        if expected == "array" and not isinstance(value, list):
            raise ValueError(f"Field '{key}' must be array")
