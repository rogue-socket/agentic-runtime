from __future__ import annotations

"""File: tests/test_workflow_versioning.py

Purpose:
Validate workflow id/version parsing, registry resolution, and persistence.
"""


import pytest

from agent_runtime.core import Executor, StepDefinition
from agent_runtime.errors import WorkflowValidationError
from agent_runtime.tools.registry import ToolRegistry
from agent_runtime.workflow import load_workflow_from_text
from agent_runtime.workflow_registry import WorkflowRegistry
from conftest import make_storage, make_memory_manager, functions_dir


def _generate_summary(inputs: dict) -> dict:
    issue = inputs.get("issue", "")
    return {"summary": f"Summary of issue: {issue}"}


def test_workflow_parses_id_and_version() -> None:
    raw = """
schema_version: v1
workflow:
  id: code_review_agent
  version: v2
steps:
  - id: generate_summary
    type: function
    function: stubs.generate_summary
"""
    workflow = load_workflow_from_text(raw, functions_dir=functions_dir())
    assert workflow["workflow_id"] == "code_review_agent"
    assert workflow["workflow_version"] == "v2"


def test_workflow_registry_latest_version_resolution(tmp_path) -> None:
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()

    (wf_dir / "triage_v1.yaml").write_text(
        """
schema_version: v1
workflow:
  id: triage
  version: v1
steps:
  - id: generate_summary
    type: function
    function: stubs.generate_summary
""",
        encoding="utf-8",
    )
    (wf_dir / "triage_v2.yaml").write_text(
        """
schema_version: v1
workflow:
  id: triage
  version: v2
steps:
  - id: generate_summary
    type: function
    function: stubs.generate_summary
""",
        encoding="utf-8",
    )

    registry = WorkflowRegistry.from_directory(str(wf_dir))

    latest = registry.get("triage")
    assert latest["workflow_version"] == "v2"

    v1 = registry.get("triage", "v1")
    assert v1["workflow_version"] == "v1"


def test_workflow_registry_latest_version_resolution_with_minor_versions(tmp_path) -> None:
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()

    (wf_dir / "triage_v1.yaml").write_text(
        """
schema_version: v1
workflow:
  id: triage
  version: v1
steps:
  - id: generate_summary
    type: function
    function: stubs.generate_summary
""",
        encoding="utf-8",
    )
    (wf_dir / "triage_v1_2.yaml").write_text(
        """
schema_version: v1
workflow:
  id: triage
  version: v1.2
steps:
  - id: generate_summary
    type: function
    function: stubs.generate_summary
""",
        encoding="utf-8",
    )
    (wf_dir / "triage_v1_10.yaml").write_text(
        """
schema_version: v1
workflow:
  id: triage
  version: v1.10
steps:
  - id: generate_summary
    type: function
    function: stubs.generate_summary
""",
        encoding="utf-8",
    )

    registry = WorkflowRegistry.from_directory(str(wf_dir))

    latest = registry.get("triage")
    assert latest["workflow_version"] == "v1.10"


def test_workflow_registry_duplicate_version_rejected() -> None:
    registry = WorkflowRegistry()
    workflow = {
        "workflow_id": "agent",
        "workflow_version": "v2",
        "steps": [],
    }
    registry.register(workflow)
    with pytest.raises(WorkflowValidationError):
        registry.register(workflow)


def test_run_persists_workflow_version() -> None:
    storage = make_storage()
    executor = Executor(
        steps=[
            StepDefinition(
                step_id="generate_summary",
                step_type="function",
                function_callable=_generate_summary,
                input_spec={"issue": "inputs.issue"},
            )
        ],
        storage=storage,
        logger=None,
        memory_manager=make_memory_manager(),
        tool_registry=ToolRegistry(),
    )

    run = executor.run(
        workflow_id="code_review_agent",
        workflow_version="v3",
        initial_state={"issue": "Login API fails for invalid token"},
    )

    loaded = storage.load_run(run.run_id)
    assert loaded.workflow_id == "code_review_agent"
    assert loaded.workflow_version == "v3"


def test_workflow_parses_optional_default_step_fields() -> None:
    raw = """
schema_version: v1
workflow:
  id: optional_flow
  version: v1
steps:
  - id: enrich
    type: function
    function: stubs.generate_summary
    optional: true
    default:
      summary: fallback
    outputs: [summary]
"""
    workflow = load_workflow_from_text(raw, functions_dir=functions_dir())
    step = workflow["steps"][0]
    assert step.optional is True
    assert step.default_output == {"summary": "fallback"}


def test_workflow_rejects_default_without_optional() -> None:
    raw = """
schema_version: v1
workflow:
  id: invalid_optional
  version: v1
steps:
  - id: enrich
    type: function
    function: stubs.generate_summary
    default:
      summary: fallback
"""
    with pytest.raises(WorkflowValidationError):
        load_workflow_from_text(raw, functions_dir=functions_dir())
