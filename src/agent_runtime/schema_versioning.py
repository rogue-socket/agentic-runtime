from __future__ import annotations

"""Shared schema/version utilities and component schema baselines.

All runtime schema-bearing components start at the same baseline (v1).
Individual component schema updates should increment minor versions
(`v1.1`, `v1.2`, ...). A broad breaking schema change can bump major
version (`v2`).
"""

from typing import Any, Dict, Tuple
import re


SCHEMA_VERSION_BASELINE = "v1"

WORKFLOW_SCHEMA_VERSION_CURRENT = SCHEMA_VERSION_BASELINE
AGENT_SCHEMA_VERSION_CURRENT = SCHEMA_VERSION_BASELINE
RUNTIME_CONFIG_SCHEMA_VERSION_CURRENT = SCHEMA_VERSION_BASELINE
STORAGE_SCHEMA_VERSION_CURRENT = SCHEMA_VERSION_BASELINE

COMPONENT_SCHEMA_VERSIONS: Dict[str, str] = {
    "workflow": WORKFLOW_SCHEMA_VERSION_CURRENT,
    "agent": AGENT_SCHEMA_VERSION_CURRENT,
    "runtime_config": RUNTIME_CONFIG_SCHEMA_VERSION_CURRENT,
    "storage": STORAGE_SCHEMA_VERSION_CURRENT,
}

_VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+)*)$", re.IGNORECASE)


def normalize_version(value: Any, *, field_name: str = "version") -> str:
    """Normalize version input to canonical `v<major>[.<minor>...]` form."""
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a version string like v1 or v1.1, got bool.")
    if isinstance(value, int):
        if value < 0:
            raise ValueError(f"{field_name} must be non-negative, got: {value}")
        return f"v{value}"
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string like v1 or v1.1, got: {type(value).__name__}")

    raw = value.strip()
    match = _VERSION_RE.fullmatch(raw)
    if not match:
        raise ValueError(f"{field_name} must match v<major>[.<minor>...], got: {value}")

    parts = match.group(1).split(".")
    normalized_parts = [str(int(part)) for part in parts]
    return f"v{'.'.join(normalized_parts)}"


def version_components(version: str) -> Tuple[int, ...]:
    """Return numeric components for semantic-like version ordering."""
    normalized = normalize_version(version)
    return tuple(int(part) for part in normalized[1:].split("."))


def parse_required_schema_version(
    raw: Dict[str, Any],
    *,
    expected_version: str,
    component_name: str,
    field_name: str = "schema_version",
) -> str:
    """Validate and normalize a required top-level schema version field."""
    raw_schema = raw.get(field_name)
    if raw_schema is None:
        raise ValueError(
            f"{component_name} {field_name} is required and must be {expected_version}."
        )

    schema_version = normalize_version(raw_schema, field_name=field_name)
    if schema_version != expected_version:
        raise ValueError(
            f"Unsupported {field_name} {schema_version} for {component_name}. "
            f"This runtime requires {expected_version}."
        )
    return schema_version
