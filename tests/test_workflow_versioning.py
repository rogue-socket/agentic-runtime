# TODO(H3-high): This file contains 8 junk auto-generated docstrings
#   that should be replaced with real descriptions or removed entirely.
from __future__ import annotations

"""File: tests/test_workflow_versioning.py

Purpose:
Validate workflow id/version parsing, registry resolution, and persistence.
"""

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
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> _storage
        >>> # Example 2
        >>> _storage
    """
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.close()
    return SQLiteStorage(tmp.name)


def _memory_manager() -> MemoryManager:
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> _memory_manager
        >>> # Example 2
        >>> _memory_manager
    """
    return MemoryManager(
        working=WorkingMemory(),
        episodic=EpisodicMemory(),
        semantic=SemanticMemory(),
        procedural=ProceduralMemory(),
    )


def _handler_registry() -> StepHandlerRegistry:
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> _handler_registry
        >>> # Example 2
        >>> _handler_registry
    """
    registry = StepHandlerRegistry()
    registry.register("generate_summary", generate_summary)
    return registry


def test_workflow_parses_id_and_version() -> None:
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> test_workflow_parses_id_and_version
        >>> # Example 2
        >>> test_workflow_parses_id_and_version
    """
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
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> test_workflow_legacy_name_compatibility
        >>> # Example 2
        >>> test_workflow_legacy_name_compatibility
    """
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
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> test_workflow_registry_latest_version_resolution
        >>> # Example 2
        >>> test_workflow_registry_latest_version_resolution
    """
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
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> test_workflow_registry_duplicate_version_rejected
        >>> # Example 2
        >>> test_workflow_registry_duplicate_version_rejected
    """
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
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> test_run_persists_workflow_version
        >>> # Example 2
        >>> test_run_persists_workflow_version
    """
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
