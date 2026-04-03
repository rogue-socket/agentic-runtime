from __future__ import annotations

import pytest

from agent_runtime.schema_versioning import (
    AGENT_SCHEMA_VERSION_CURRENT,
    COMPONENT_SCHEMA_VERSIONS,
    RUNTIME_CONFIG_SCHEMA_VERSION_CURRENT,
    SCHEMA_VERSION_BASELINE,
    STORAGE_SCHEMA_VERSION_CURRENT,
    WORKFLOW_SCHEMA_VERSION_CURRENT,
    normalize_version,
    parse_required_schema_version,
    version_components,
)


def test_all_component_schema_versions_share_same_baseline() -> None:
    """Function implementation."""
    assert WORKFLOW_SCHEMA_VERSION_CURRENT == SCHEMA_VERSION_BASELINE
    assert AGENT_SCHEMA_VERSION_CURRENT == SCHEMA_VERSION_BASELINE
    assert RUNTIME_CONFIG_SCHEMA_VERSION_CURRENT == SCHEMA_VERSION_BASELINE
    assert STORAGE_SCHEMA_VERSION_CURRENT == SCHEMA_VERSION_BASELINE
    assert set(COMPONENT_SCHEMA_VERSIONS.values()) == {SCHEMA_VERSION_BASELINE}


def test_normalize_version_supports_minor_increments() -> None:
    """Function implementation."""
    assert normalize_version("v1") == "v1"
    assert normalize_version("1") == "v1"
    assert normalize_version("v1.1") == "v1.1"
    assert normalize_version("1.20") == "v1.20"


def test_normalize_version_rejects_invalid_formats() -> None:
    """Function implementation."""
    with pytest.raises(ValueError):
        normalize_version("version1")
    with pytest.raises(ValueError):
        normalize_version("v1-beta")


def test_version_components_support_numeric_ordering() -> None:
    """Function implementation."""
    assert version_components("v1.10") > version_components("v1.2")
    assert version_components("v2") > version_components("v1.99")


def test_parse_required_schema_version_validates_expected_value() -> None:
    """Function implementation."""
    raw = {"schema_version": "v1"}
    parsed = parse_required_schema_version(
        raw,
        expected_version="v1",
        component_name="workflow",
    )
    assert parsed == "v1"

    with pytest.raises(ValueError, match="This runtime requires v1"):
        parse_required_schema_version(
            {"schema_version": "v2"},
            expected_version="v1",
            component_name="workflow",
        )
