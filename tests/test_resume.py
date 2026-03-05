from __future__ import annotations

import tempfile
from typing import Any, Dict

import pytest

from agent_runtime.core import Executor, StepDefinition, StepStatus
from agent_runtime.errors import StepExecutionError
from agent_runtime.memory.base import MemoryManager
from agent_runtime.memory.working import WorkingMemory
from agent_runtime.memory.episodic import EpisodicMemory
from agent_runtime.memory.semantic import SemanticMemory
from agent_runtime.memory.procedural import ProceduralMemory
from agent_runtime.resume import determine_resume_step, validate_resume
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


def test_resume_from_failed_step() -> None:
    storage = _storage()
    tool_registry = ToolRegistry()

    def step_one(state: Dict[str, Any]) -> Dict[str, Any]:
        return {"one": True}

    def step_two_fail(state: Dict[str, Any]) -> Dict[str, Any]:
        raise ValueError("boom")

    steps = [
        StepDefinition(step_id="step_one", step_type="model", handler=step_one),
        StepDefinition(step_id="step_two", step_type="model", handler=step_two_fail),
    ]

    executor = Executor(steps, storage, None, _memory_manager(), tool_registry)
    run = executor.run("wf", {"issue": "x"})
    assert run.status == StepStatus.FAILED

    executions = storage.load_steps(run.run_id)
    resume_step = determine_resume_step(steps, executions)
    assert resume_step == "step_two"

    def step_two_ok(state: Dict[str, Any]) -> Dict[str, Any]:
        return {"two": True}

    resume_steps = [
        StepDefinition(step_id="step_one", step_type="model", handler=step_one),
        StepDefinition(step_id="step_two", step_type="model", handler=step_two_ok),
    ]

    resume_executor = Executor(resume_steps, storage, None, _memory_manager(), tool_registry)
    state = storage.load_latest_state(run.run_id)
    state_version = storage.load_latest_state_version(run.run_id)
    resumed = resume_executor.resume(run, state, "step_two", on_error="fail_fast", state_version=state_version)
    assert resumed.status == StepStatus.COMPLETED
    assert resumed.state.data["steps"]["step_two"]["two"] is True


def test_validate_resume_blocks_completed() -> None:
    with pytest.raises(StepExecutionError):
        validate_resume(StepStatus.COMPLETED)


def test_validate_resume_blocks_running() -> None:
    with pytest.raises(StepExecutionError):
        validate_resume(StepStatus.RUNNING)
