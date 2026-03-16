from __future__ import annotations

"""File: tests/test_runtime.py

Purpose:
Validate core runtime execution flows and persistence hooks.

Description:
Covers model/tool execution, workflow validation, retries, state version
tracking, and memory hook invocation behavior.
"""

import asyncio
import sqlite3
import tempfile
from typing import Any, Dict

import pytest

from agent_runtime.core import Executor, RetryPolicy, StepDefinition, StepStatus
from agent_runtime.errors import WorkflowValidationError
from agent_runtime.memory.base import MemoryManager
from agent_runtime.storage.sqlite import SQLiteStorage
from agent_runtime.steps import StepHandlerRegistry, generate_summary
from agent_runtime.tools.registry import ToolRegistry
from agent_runtime.tools.base import ToolResult, RuntimeContext
from agent_runtime.workflow import load_workflow
from agent_runtime.memory.working import WorkingMemory
from agent_runtime.memory.episodic import EpisodicMemory
from agent_runtime.memory.semantic import SemanticMemory
from agent_runtime.memory.procedural import ProceduralMemory


class CounterMemory:
    """Auto-generated documentation for this class.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> CounterMemory
        >>> # Example 2
        >>> CounterMemory
    """
    def __init__(self) -> None:
        """Auto-generated documentation for this callable.
        
        Describes purpose, expected inputs/outputs, and behavior in this module.
        
        Example:
            >>> # Example 1
            >>> __init__
            >>> # Example 2
            >>> __init__
        """
        self.read_calls = 0
        self.write_calls = 0

    def read(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Auto-generated documentation for this callable.
        
        Describes purpose, expected inputs/outputs, and behavior in this module.
        
        Example:
            >>> # Example 1
            >>> read
            >>> # Example 2
            >>> read
        """
        self.read_calls += 1
        return {}

    def write(self, payload: Dict[str, Any]) -> None:
        """Auto-generated documentation for this callable.
        
        Describes purpose, expected inputs/outputs, and behavior in this module.
        
        Example:
            >>> # Example 1
            >>> write
            >>> # Example 2
            >>> write
        """
        self.write_calls += 1


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


def test_model_step_success() -> None:
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> test_model_step_success
        >>> # Example 2
        >>> test_model_step_success
    """
    storage = _storage()
    tool_registry = ToolRegistry()
    logger = None

    steps = [
        StepDefinition(
            step_id="generate_summary",
            step_type="model",
            handler=generate_summary,
            input_spec={"issue": "inputs.issue"},
        )
    ]
    executor = Executor(steps, storage, logger, _memory_manager(), tool_registry)

    run = executor.run("wf", {"issue": "Login API fails for invalid token"})
    assert run.status == StepStatus.COMPLETED
    assert "generate_summary" in run.state.data["steps"]
    assert "summary" in run.state.data["steps"]["generate_summary"]


def test_model_step_missing_issue() -> None:
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> test_model_step_missing_issue
        >>> # Example 2
        >>> test_model_step_missing_issue
    """
    storage = _storage()
    tool_registry = ToolRegistry()
    logger = None

    steps = [
        StepDefinition(
            step_id="generate_summary",
            step_type="model",
            handler=generate_summary,
            input_spec={"issue": "inputs.issue"},
        )
    ]
    executor = Executor(steps, storage, logger, _memory_manager(), tool_registry)

    run = executor.run("wf", {})
    assert run.status == StepStatus.FAILED
    assert run.error is not None


def test_tool_step_success() -> None:
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> test_tool_step_success
        >>> # Example 2
        >>> test_tool_step_success
    """
    storage = _storage()
    tool_registry = ToolRegistry()

    class EchoTool:
        """Auto-generated documentation for this class.
        
        Describes purpose, expected inputs/outputs, and behavior in this module.
        
        Example:
            >>> # Example 1
            >>> EchoTool
            >>> # Example 2
            >>> EchoTool
        """
        name = "tools.echo"
        description = "echo"
        input_schema = {"type": "object", "properties": {"x": {"type": "number"}}}
        timeout = None
        retries = None

        async def execute(self, input: Dict[str, Any], context: RuntimeContext) -> ToolResult:
            """Auto-generated documentation for this callable.
            
            Describes purpose, expected inputs/outputs, and behavior in this module.
            
            Example:
                >>> # Example 1
                >>> execute
                >>> # Example 2
                >>> execute
            """
            return ToolResult(success=True, output={"x": input["x"]}, error=None, metadata=None)

    tool_registry.register(EchoTool())

    steps = [StepDefinition(step_id="echo", step_type="tool", tool_name="tools.echo", raw_input={"x": 1})]
    executor = Executor(steps, storage, None, _memory_manager(), tool_registry)

    run = executor.run("wf", {"issue": "x"})
    assert run.status == StepStatus.COMPLETED
    assert run.state.data["steps"]["echo"]["x"] == 1


def test_run_async_executes_tool_step() -> None:
    """Ensure async execution path runs tool steps successfully."""
    storage = _storage()
    tool_registry = ToolRegistry()

    class EchoTool:
        name = "tools.echo"
        description = "echo"
        input_schema = {"type": "object", "properties": {"x": {"type": "number"}}}
        timeout = None
        retries = None

        async def execute(self, input: Dict[str, Any], context: RuntimeContext) -> ToolResult:
            return ToolResult(success=True, output={"x": input["x"]}, error=None, metadata=None)

    tool_registry.register(EchoTool())
    steps = [StepDefinition(step_id="echo", step_type="tool", tool_name="tools.echo", raw_input={"x": 2})]
    executor = Executor(steps, storage, None, _memory_manager(), tool_registry)

    async def _run() -> None:
        run = await executor.run_async("wf", {"issue": "x"})
        assert run.status == StepStatus.COMPLETED
        assert run.state.data["steps"]["echo"]["x"] == 2

    asyncio.run(_run())


def test_run_raises_inside_event_loop() -> None:
    """Sync run should refuse to execute inside a running event loop."""
    storage = _storage()
    tool_registry = ToolRegistry()
    steps = [
        StepDefinition(
            step_id="generate_summary",
            step_type="model",
            handler=generate_summary,
            input_spec={"issue": "inputs.issue"},
        )
    ]
    executor = Executor(steps, storage, None, _memory_manager(), tool_registry)

    async def _run() -> None:
        with pytest.raises(RuntimeError):
            executor.run("wf", {"issue": "Login API fails for invalid token"})

    asyncio.run(_run())


def test_workflow_yaml_validation(tmp_path) -> None:
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> test_workflow_yaml_validation
        >>> # Example 2
        >>> test_workflow_yaml_validation
    """
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("name: x\nsteps: {}\n", encoding="utf-8")

    registry = StepHandlerRegistry()
    registry.register("generate_summary", generate_summary)

    with pytest.raises(WorkflowValidationError):
        load_workflow(str(bad_yaml), registry)


def test_state_versioning() -> None:
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> test_state_versioning
        >>> # Example 2
        >>> test_state_versioning
    """
    storage = _storage()
    tool_registry = ToolRegistry()

    steps = [
        StepDefinition(
            step_id="generate_summary",
            step_type="model",
            handler=generate_summary,
            input_spec={"issue": "inputs.issue"},
        )
    ]
    executor = Executor(steps, storage, None, _memory_manager(), tool_registry)

    run = executor.run("wf", {"issue": "Login API fails for invalid token"})
    assert run.status == StepStatus.COMPLETED

    conn = sqlite3.connect(storage.db_path)
    count = conn.execute("SELECT COUNT(*) FROM state_versions WHERE run_id = ?", (run.run_id,)).fetchone()[0]
    conn.close()

    assert count == 2


def test_memory_hooks_invoked() -> None:
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> test_memory_hooks_invoked
        >>> # Example 2
        >>> test_memory_hooks_invoked
    """
    storage = _storage()
    tool_registry = ToolRegistry()

    working = CounterMemory()
    episodic = CounterMemory()
    semantic = CounterMemory()
    procedural = CounterMemory()
    memory_manager = MemoryManager(working, episodic, semantic, procedural)

    steps = [
        StepDefinition(
            step_id="generate_summary",
            step_type="model",
            handler=generate_summary,
            input_spec={"issue": "inputs.issue"},
        )
    ]
    executor = Executor(steps, storage, None, memory_manager, tool_registry)

    run = executor.run("wf", {"issue": "Login API fails for invalid token"})
    assert run.status == StepStatus.COMPLETED
    assert working.read_calls == 1
    assert episodic.read_calls == 1
    assert semantic.read_calls == 1
    assert procedural.read_calls == 1
    assert working.write_calls == 1
    assert episodic.write_calls == 1
    assert semantic.write_calls == 1
    assert procedural.write_calls == 1


def test_retry_policy_succeeds() -> None:
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> test_retry_policy_succeeds
        >>> # Example 2
        >>> test_retry_policy_succeeds
    """
    storage = _storage()
    tool_registry = ToolRegistry()
    logger = None

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
            retry=RetryPolicy(attempts=2, backoff="fixed", initial_delay=0),
        )
    ]
    executor = Executor(steps, storage, logger, _memory_manager(), tool_registry)

    run = executor.run("wf", {"issue": "x"})
    assert run.status == StepStatus.COMPLETED
    assert run.state.data["steps"]["flaky"]["ok"] is True


def test_state_snapshots_persisted() -> None:
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> test_state_snapshots_persisted
        >>> # Example 2
        >>> test_state_snapshots_persisted
    """
    storage = _storage()
    tool_registry = ToolRegistry()

    steps = [
        StepDefinition(
            step_id="generate_summary",
            step_type="model",
            handler=generate_summary,
            input_spec={"issue": "inputs.issue"},
        )
    ]
    executor = Executor(steps, storage, None, _memory_manager(), tool_registry)

    run = executor.run("wf", {"issue": "Login API fails for invalid token"})
    assert run.status == StepStatus.COMPLETED

    execs = storage.load_steps(run.run_id)
    assert execs[0].state_before is not None
    assert execs[0].state_after is not None
