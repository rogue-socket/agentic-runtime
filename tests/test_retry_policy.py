from __future__ import annotations

"""File: tests/test_retry_policy.py

Purpose:
Test retry policy semantics across successful and exhausted attempts.
"""

import tempfile
from typing import Any, Dict

import pytest

from agent_runtime.core import Executor, RetryPolicy, StepDefinition, StepStatus
from agent_runtime.memory.base import MemoryManager
from agent_runtime.memory.episodic import EpisodicMemory
from agent_runtime.memory.procedural import ProceduralMemory
from agent_runtime.memory.semantic import SemanticMemory
from agent_runtime.memory.working import WorkingMemory
from agent_runtime.storage.sqlite import SQLiteStorage
from agent_runtime.tools.registry import ToolRegistry
from agent_runtime.workflow import load_workflow


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


def test_retry_success_attempt_count() -> None:
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> test_retry_success_attempt_count
        >>> # Example 2
        >>> test_retry_success_attempt_count
    """
    storage = _storage()
    tool_registry = ToolRegistry()

    attempts = {"count": 0}

    def flaky_handler(state: Dict[str, Any]) -> Dict[str, Any]:
        """Auto-generated documentation for this callable.
        
        Describes purpose, expected inputs/outputs, and behavior in this module.
        
        Example:
            >>> # Example 1
            >>> flaky_handler
            >>> # Example 2
            >>> flaky_handler
        """
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise ValueError("transient")
        return {"ok": True}

    steps = [
        StepDefinition(
            step_id="flaky",
            step_type="model",
            handler=flaky_handler,
            input_spec={"issue": "inputs.issue"},
            retry=RetryPolicy(attempts=2, backoff="fixed", initial_delay=0),
        )
    ]

    executor = Executor(steps, storage, None, _memory_manager(), tool_registry)
    run = executor.run("wf", {"issue": "x"})
    assert run.status == StepStatus.COMPLETED

    execs = storage.load_steps(run.run_id)
    assert execs[-1].attempt_count == 2


def test_retry_exhaustion_marks_failed() -> None:
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> test_retry_exhaustion_marks_failed
        >>> # Example 2
        >>> test_retry_exhaustion_marks_failed
    """
    storage = _storage()
    tool_registry = ToolRegistry()

    def always_fail(state: Dict[str, Any]) -> Dict[str, Any]:
        """Auto-generated documentation for this callable.
        
        Describes purpose, expected inputs/outputs, and behavior in this module.
        
        Example:
            >>> # Example 1
            >>> always_fail
            >>> # Example 2
            >>> always_fail
        """
        raise ValueError("fail")

    steps = [
        StepDefinition(
            step_id="failer",
            step_type="model",
            handler=always_fail,
            input_spec={"issue": "inputs.issue"},
            retry=RetryPolicy(attempts=3, backoff="fixed", initial_delay=0),
        )
    ]

    executor = Executor(steps, storage, None, _memory_manager(), tool_registry)
    run = executor.run("wf", {"issue": "x"})
    assert run.status == StepStatus.FAILED

    execs = storage.load_steps(run.run_id)
    assert execs[-1].attempt_count == 3


def test_no_retry_defaults_to_one_attempt() -> None:
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> test_no_retry_defaults_to_one_attempt
        >>> # Example 2
        >>> test_no_retry_defaults_to_one_attempt
    """
    storage = _storage()
    tool_registry = ToolRegistry()

    def ok(state: Dict[str, Any]) -> Dict[str, Any]:
        """Auto-generated documentation for this callable.
        
        Describes purpose, expected inputs/outputs, and behavior in this module.
        
        Example:
            >>> # Example 1
            >>> ok
            >>> # Example 2
            >>> ok
        """
        return {"ok": True}

    steps = [StepDefinition(step_id="ok", step_type="model", handler=ok, input_spec={"issue": "inputs.issue"})]
    executor = Executor(steps, storage, None, _memory_manager(), tool_registry)
    run = executor.run("wf", {"issue": "x"})

    execs = storage.load_steps(run.run_id)
    assert execs[-1].attempt_count == 1


def test_workflow_retry_validation(tmp_path) -> None:
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> test_workflow_retry_validation
        >>> # Example 2
        >>> test_workflow_retry_validation
    """
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text(
        "name: wf\nsteps:\n  - id: a\n    type: model\n    handler: generate_summary\n    retry:\n      attempts: 0\n",
        encoding="utf-8",
    )

    from agent_runtime.steps import StepHandlerRegistry, generate_summary

    reg = StepHandlerRegistry()
    reg.register("generate_summary", generate_summary)

    with pytest.raises(Exception):
        load_workflow(str(bad_yaml), reg)
