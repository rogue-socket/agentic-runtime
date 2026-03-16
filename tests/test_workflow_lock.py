"""Tests for workflow integrity lock on resume."""

from __future__ import annotations

import tempfile
from typing import Any, Dict

import pytest

from agent_runtime.core import Executor, StepDefinition, StepStatus
from agent_runtime.errors import WorkflowIntegrityError
from agent_runtime.memory.base import MemoryManager
from agent_runtime.memory.working import WorkingMemory
from agent_runtime.memory.episodic import EpisodicMemory
from agent_runtime.memory.semantic import SemanticMemory
from agent_runtime.memory.procedural import ProceduralMemory
from agent_runtime.storage.sqlite import SQLiteStorage
from agent_runtime.tools.registry import ToolRegistry


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


def test_resume_blocked_when_workflow_hash_differs() -> None:
    """Resume raises WorkflowIntegrityError if workflow hash changed."""
    storage = _storage()
    tool_registry = ToolRegistry()

    def step_one(state: Dict[str, Any]) -> Dict[str, Any]:
        return {"one": True}

    def step_two_fail(state: Dict[str, Any]) -> Dict[str, Any]:
        raise ValueError("boom")

    steps = [
        StepDefinition(step_id="s1", step_type="model", handler=step_one),
        StepDefinition(step_id="s2", step_type="model", handler=step_two_fail),
    ]

    executor = Executor(steps, storage, None, _memory_manager(), tool_registry)
    run = executor.run("wf", {"issue": "x"}, workflow_hash="hash_original")
    assert run.status == StepStatus.FAILED

    # Try resuming with a different workflow hash
    def step_two_ok(state: Dict[str, Any]) -> Dict[str, Any]:
        return {"two": True}

    resume_steps = [
        StepDefinition(step_id="s1", step_type="model", handler=step_one),
        StepDefinition(step_id="s2", step_type="model", handler=step_two_ok),
    ]
    resume_executor = Executor(resume_steps, storage, None, _memory_manager(), tool_registry)
    state = storage.load_latest_state(run.run_id)
    state_version = storage.load_latest_state_version(run.run_id)

    with pytest.raises(WorkflowIntegrityError):
        resume_executor.resume(
            run=run,
            resume_state=state,
            start_step_id="s2",
            on_error="fail_fast",
            state_version=state_version,
            workflow_hash="hash_modified",
        )


def test_resume_allowed_when_workflow_hash_matches() -> None:
    """Resume proceeds when workflow hash matches the original."""
    storage = _storage()
    tool_registry = ToolRegistry()

    def step_one(state: Dict[str, Any]) -> Dict[str, Any]:
        return {"one": True}

    def step_two_fail(state: Dict[str, Any]) -> Dict[str, Any]:
        raise ValueError("boom")

    steps = [
        StepDefinition(step_id="s1", step_type="model", handler=step_one),
        StepDefinition(step_id="s2", step_type="model", handler=step_two_fail),
    ]

    executor = Executor(steps, storage, None, _memory_manager(), tool_registry)
    run = executor.run("wf", {"issue": "x"}, workflow_hash="hash_v1")
    assert run.status == StepStatus.FAILED

    def step_two_ok(state: Dict[str, Any]) -> Dict[str, Any]:
        return {"two": True}

    resume_steps = [
        StepDefinition(step_id="s1", step_type="model", handler=step_one),
        StepDefinition(step_id="s2", step_type="model", handler=step_two_ok),
    ]
    resume_executor = Executor(resume_steps, storage, None, _memory_manager(), tool_registry)
    state = storage.load_latest_state(run.run_id)
    state_version = storage.load_latest_state_version(run.run_id)

    resumed = resume_executor.resume(
        run=run,
        resume_state=state,
        start_step_id="s2",
        on_error="fail_fast",
        state_version=state_version,
        workflow_hash="hash_v1",
    )
    assert resumed.status == StepStatus.COMPLETED


def test_resume_allowed_when_no_hash_stored() -> None:
    """Resume proceeds when original run has no workflow hash (legacy)."""
    storage = _storage()
    tool_registry = ToolRegistry()

    def step_one(state: Dict[str, Any]) -> Dict[str, Any]:
        return {"one": True}

    def step_two_fail(state: Dict[str, Any]) -> Dict[str, Any]:
        raise ValueError("boom")

    steps = [
        StepDefinition(step_id="s1", step_type="model", handler=step_one),
        StepDefinition(step_id="s2", step_type="model", handler=step_two_fail),
    ]

    executor = Executor(steps, storage, None, _memory_manager(), tool_registry)
    # No workflow_hash passed -> run.workflow_hash is None
    run = executor.run("wf", {"issue": "x"})
    assert run.status == StepStatus.FAILED

    def step_two_ok(state: Dict[str, Any]) -> Dict[str, Any]:
        return {"two": True}

    resume_steps = [
        StepDefinition(step_id="s1", step_type="model", handler=step_one),
        StepDefinition(step_id="s2", step_type="model", handler=step_two_ok),
    ]
    resume_executor = Executor(resume_steps, storage, None, _memory_manager(), tool_registry)
    state = storage.load_latest_state(run.run_id)
    state_version = storage.load_latest_state_version(run.run_id)

    # Should not raise even with a hash provided — no stored hash to compare against
    resumed = resume_executor.resume(
        run=run,
        resume_state=state,
        start_step_id="s2",
        on_error="fail_fast",
        state_version=state_version,
        workflow_hash="any_hash",
    )
    assert resumed.status == StepStatus.COMPLETED
