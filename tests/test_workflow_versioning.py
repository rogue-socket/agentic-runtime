from __future__ import annotations

import tempfile

import pytest

from agent_runtime.core import Executor, StepDefinition
from agent_runtime.errors import WorkflowValidationError
from agent_runtime.memory.base import MemoryManager
from agent_runtime.memory.episodic import EpisodicMemory
from agent_runtime.memory.procedural import ProceduralMemory
from agent_runtime.memory.semantic import SemanticMemory
from agent_runtime.memory.working import WorkingMemory
from agent_runtime.steps import StepHandlerRegistry, generate_summary
from agent_runtime.storage.sqlite import SQLiteStorage
from agent_runtime.tools.registry import ToolRegistry
from agent_runtime.workflow import load_workflow_from_text
from agent_runtime.workflow_registry import WorkflowRegistry


def _storage() -> SQLiteStorage:
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.close()
    return SQLiteStorage(tmp.name)


def _memory_manager() -> MemoryManager:
    return MemoryManager(
        working=WorkingMemory(),
        episodic=EpisodicMemory(),
        semantic=SemanticMemory(),
        procedural=ProceduralMemory(),
    )


def _handler_registry() -> StepHandlerRegistry:
    registry = StepHandlerRegistry()
    registry.register("generate_summary", generate_summary)
    return registry


def test_workflow_parses_id_and_version() -> None:
    raw = """
workflow:
  id: code_review_agent
  version: v2
steps:
  - id: generate_summary
    type: model
    handler: generate_summary
"""
    workflow = load_workflow_from_text(raw, _handler_registry())
    assert workflow["workflow_id"] == "code_review_agent"
    assert workflow["workflow_version"] == "v2"


def test_workflow_legacy_name_compatibility() -> None:
    raw = """
name: legacy_workflow
steps:
  - id: generate_summary
    type: model
    handler: generate_summary
"""
    workflow = load_workflow_from_text(raw, _handler_registry())
    assert workflow["workflow_id"] == "legacy_workflow"
    assert workflow["workflow_version"] is None


def test_workflow_registry_latest_version_resolution(tmp_path) -> None:
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()

    (wf_dir / "triage_v1.yaml").write_text(
        """
workflow:
  id: triage
  version: v1
steps:
  - id: generate_summary
    type: model
    handler: generate_summary
""",
        encoding="utf-8",
    )
    (wf_dir / "triage_v2.yaml").write_text(
        """
workflow:
  id: triage
  version: v2
steps:
  - id: generate_summary
    type: model
    handler: generate_summary
""",
        encoding="utf-8",
    )

    registry = WorkflowRegistry.from_directory(str(wf_dir), _handler_registry())

    latest = registry.get("triage")
    assert latest["workflow_version"] == "v2"

    v1 = registry.get("triage", "v1")
    assert v1["workflow_version"] == "v1"


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
    storage = _storage()
    executor = Executor(
        steps=[
            StepDefinition(
                step_id="generate_summary",
                step_type="model",
                handler=generate_summary,
                input_spec={"issue": "inputs.issue"},
            )
        ],
        storage=storage,
        logger=None,
        memory_manager=_memory_manager(),
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
