from __future__ import annotations

"""File: src/agent_runtime/tools/validation.py

Purpose:
Provide lightweight schema validation for tool input payloads.

Description:
Supports a constrained subset of JSON-schema-like type checks used by
the runtime before dispatching tool execution.
"""

from typing import Any, Dict


def validate_input(payload: Dict[str, Any], schema: Dict[str, Any]) -> None:
    """Validate payload fields against a basic object schema.

    # TODO: BUG
    # The validator ignores `required` keys entirely, allowing calls with
    # missing mandatory fields. Suggested fix: enforce `required` array and
    # emit clear validation errors before tool execution.
    """
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
