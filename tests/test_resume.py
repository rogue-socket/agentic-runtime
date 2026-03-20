# TODO(H3-high): This file contains 8 junk auto-generated docstrings
#   that should be replaced with real descriptions or removed entirely.
from __future__ import annotations

"""File: tests/test_resume.py

Purpose:
Validate resume eligibility checks and resume execution flow.
"""

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


def test_resume_from_failed_step() -> None:
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> test_resume_from_failed_step
        >>> # Example 2
        >>> test_resume_from_failed_step
    """
    storage = _storage()
    tool_registry = ToolRegistry()

    def step_one(inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Auto-generated documentation for this callable.
        
        Describes purpose, expected inputs/outputs, and behavior in this module.
        
        Example:
            >>> # Example 1
            >>> step_one
            >>> # Example 2
            >>> step_one
        """
        return {"one": True}

    def step_two_fail(inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Auto-generated documentation for this callable.
        
        Describes purpose, expected inputs/outputs, and behavior in this module.
        
        Example:
            >>> # Example 1
            >>> step_two_fail
            >>> # Example 2
            >>> step_two_fail
        """
        raise ValueError("boom")

    steps = [
        StepDefinition(step_id="step_one", step_type="function", function_callable=step_one),
        StepDefinition(step_id="step_two", step_type="function", function_callable=step_two_fail),
    ]

    executor = Executor(steps, storage, None, _memory_manager(), tool_registry)
    run = executor.run("wf", {"issue": "x"})
    assert run.status == StepStatus.FAILED

    executions = storage.load_steps(run.run_id)
    resume_step = determine_resume_step(steps, executions)
    assert resume_step == "step_two"

    def step_two_ok(inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Auto-generated documentation for this callable.
        
        Describes purpose, expected inputs/outputs, and behavior in this module.
        
        Example:
            >>> # Example 1
            >>> step_two_ok
            >>> # Example 2
            >>> step_two_ok
        """
        return {"two": True}

    resume_steps = [
        StepDefinition(step_id="step_one", step_type="function", function_callable=step_one),
        StepDefinition(step_id="step_two", step_type="function", function_callable=step_two_ok),
    ]

    resume_executor = Executor(resume_steps, storage, None, _memory_manager(), tool_registry)
    state = storage.load_latest_state(run.run_id)
    state_version = storage.load_latest_state_version(run.run_id)
    resumed = resume_executor.resume(run, state, "step_two", on_error="fail_fast", state_version=state_version)
    assert resumed.status == StepStatus.COMPLETED
    assert resumed.state.data["steps"]["step_two"]["two"] is True


def test_validate_resume_blocks_completed() -> None:
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> test_validate_resume_blocks_completed
        >>> # Example 2
        >>> test_validate_resume_blocks_completed
    """
    with pytest.raises(StepExecutionError):
        validate_resume(StepStatus.COMPLETED)


def test_validate_resume_blocks_running() -> None:
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> test_validate_resume_blocks_running
        >>> # Example 2
        >>> test_validate_resume_blocks_running
    """
    with pytest.raises(StepExecutionError):
        validate_resume(StepStatus.RUNNING)


def test_validate_resume_blocks_completed_with_errors() -> None:
    """COMPLETED_WITH_ERRORS runs should not be resumable (L4 fix)."""
    with pytest.raises(StepExecutionError):
        validate_resume(StepStatus.COMPLETED_WITH_ERRORS)
