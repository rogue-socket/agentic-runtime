from __future__ import annotations

"""File: tests/test_resume.py

Purpose:
Validate resume eligibility checks and resume execution flow.
"""

from typing import Any, Dict

import pytest

from agent_runtime.core import Executor, StepDefinition, StepStatus
from agent_runtime.errors import StepExecutionError
from agent_runtime.resume import determine_resume_step, validate_resume
from agent_runtime.tools.registry import ToolRegistry
from conftest import make_storage, make_memory_manager


def test_resume_from_failed_step() -> None:
    storage = make_storage()
    tool_registry = ToolRegistry()

    def step_one(inputs: Dict[str, Any]) -> Dict[str, Any]:
        return {"one": True}

    def step_two_fail(inputs: Dict[str, Any]) -> Dict[str, Any]:
        raise ValueError("boom")

    steps = [
        StepDefinition(step_id="step_one", step_type="function", function_callable=step_one),
        StepDefinition(step_id="step_two", step_type="function", function_callable=step_two_fail),
    ]

    executor = Executor(steps, storage, None, make_memory_manager(), tool_registry)
    run = executor.run("wf", {"issue": "x"}, workflow_hash="hash_v1")
    assert run.status == StepStatus.FAILED

    executions = storage.load_steps(run.run_id)
    resume_step = determine_resume_step(steps, executions)
    assert resume_step == "step_two"

    def step_two_ok(inputs: Dict[str, Any]) -> Dict[str, Any]:
        return {"two": True}

    resume_steps = [
        StepDefinition(step_id="step_one", step_type="function", function_callable=step_one),
        StepDefinition(step_id="step_two", step_type="function", function_callable=step_two_ok),
    ]

    resume_executor = Executor(resume_steps, storage, None, make_memory_manager(), tool_registry)
    state = storage.load_latest_state(run.run_id)
    state_version = storage.load_latest_state_version(run.run_id)
    resumed = resume_executor.resume(
        run,
        state,
        "step_two",
        on_error="fail_fast",
        state_version=state_version,
        workflow_hash="hash_v1",
    )
    assert resumed.status == StepStatus.COMPLETED
    assert resumed.state.data["steps"]["step_two"]["two"] is True


def test_validate_resume_blocks_completed() -> None:
    with pytest.raises(StepExecutionError):
        validate_resume(StepStatus.COMPLETED)


def test_validate_resume_blocks_running() -> None:
    with pytest.raises(StepExecutionError):
        validate_resume(StepStatus.RUNNING)


def test_validate_resume_blocks_completed_with_errors() -> None:
    """COMPLETED_WITH_ERRORS runs should not be resumable (L4 fix)."""
    with pytest.raises(StepExecutionError):
        validate_resume(StepStatus.COMPLETED_WITH_ERRORS)
