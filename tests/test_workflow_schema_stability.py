from __future__ import annotations

"""Workflow schema versioning strictness tests."""

import pytest

from agent_runtime.errors import WorkflowValidationError
from agent_runtime.workflow import WORKFLOW_SCHEMA_VERSION_CURRENT, load_workflow_from_text


def test_schema_v1_parses() -> None:
    raw = """
schema_version: v1
workflow:
  id: stable_flow
  version: v1
steps:
  - id: ping
    type: tool
    tool: tools.echo
    inputs:
      message: "hi"
"""
    workflow = load_workflow_from_text(raw)
    assert workflow["workflow_schema_version"] == "v1"


def test_missing_schema_version_is_rejected() -> None:
    raw = """
workflow:
  id: missing_schema
  version: v1
steps:
  - id: ping
    type: tool
    tool: tools.echo
    inputs:
      message: "hi"
"""
    with pytest.raises(WorkflowValidationError, match="schema_version is required"):
        load_workflow_from_text(raw)


def test_legacy_name_version_identity_is_rejected() -> None:
    raw = """
schema_version: v1
name: old_style_flow
version: v7
steps:
  - id: ping
    type: tool
    tool: tools.echo
    inputs:
      message: "legacy"
"""
    with pytest.raises(WorkflowValidationError, match="top-level workflow mapping"):
        load_workflow_from_text(raw)


def test_rejects_non_current_schema_version() -> None:
    raw = """
schema_version: v2
workflow:
  id: old_flow
  version: v1
steps:
  - id: ping
    type: tool
    tool: tools.echo
"""
    with pytest.raises(WorkflowValidationError, match="This runtime requires v"):
        load_workflow_from_text(raw)


def test_step_input_field_is_rejected() -> None:
    raw = """
schema_version: v1
workflow:
  id: bad_step_input
  version: v1
steps:
  - id: ping
    type: tool
    tool: tools.echo
    input:
      message: "hello"
"""
    with pytest.raises(WorkflowValidationError, match="field 'input' is not supported"):
        load_workflow_from_text(raw)


def test_constant_tracks_current_schema() -> None:
    assert WORKFLOW_SCHEMA_VERSION_CURRENT == "v1"
