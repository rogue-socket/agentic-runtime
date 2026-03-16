from __future__ import annotations

"""File: tests/test_replay.py

Purpose:
Validate deterministic replay behavior and replay safety guarantees.
"""

import tempfile
from typing import Any, Dict

import pytest

from agent_runtime.core import Executor, StepDefinition
from agent_runtime.memory.base import MemoryManager
from agent_runtime.memory.episodic import EpisodicMemory
from agent_runtime.memory.procedural import ProceduralMemory
from agent_runtime.memory.semantic import SemanticMemory
from agent_runtime.memory.working import WorkingMemory
from agent_runtime.replay import RunReplayer
from agent_runtime.errors import ReplayDataMissingError
from agent_runtime.storage.sqlite import SQLiteStorage
from agent_runtime.tools.base import RuntimeContext, ToolResult
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


class CountingTool:
    """Auto-generated documentation for this class.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> CountingTool
        >>> # Example 2
        >>> CountingTool
    """
    name = "tools.counting"
    description = "counts executions"
    input_schema = {"type": "object", "properties": {"message": {"type": "string"}}}
    timeout = None
    retries = None

    def __init__(self) -> None:
        """Auto-generated documentation for this callable.
        
        Describes purpose, expected inputs/outputs, and behavior in this module.
        
        Example:
            >>> # Example 1
            >>> __init__
            >>> # Example 2
            >>> __init__
        """
        self.calls = 0

    async def execute(self, input: Dict[str, Any], context: RuntimeContext) -> ToolResult:
        """Auto-generated documentation for this callable.
        
        Describes purpose, expected inputs/outputs, and behavior in this module.
        
        Example:
            >>> # Example 1
            >>> execute
            >>> # Example 2
            >>> execute
        """
        self.calls += 1
        return ToolResult(success=True, output={"message": input.get("message")}, error=None, metadata=None)


def test_basic_replay() -> None:
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> test_basic_replay
        >>> # Example 2
        >>> test_basic_replay
    """
    storage = _storage()
    tool_registry = ToolRegistry()
    tool = CountingTool()
    tool_registry.register(tool)

    steps = [StepDefinition(step_id="echo", step_type="tool", tool_name="tools.counting", raw_input={"message": "x"})]
    executor = Executor(steps, storage, None, _memory_manager(), tool_registry)
    run = executor.run("wf", {"issue": "x"})

    events = []
    replayer = RunReplayer(storage=storage, printer=events.append)
    result = replayer.replay(run.run_id)

    assert result.run_id == run.run_id
    assert result.steps_replayed == 1
    assert any("Replay complete" in e for e in events)


def test_replay_state_matches() -> None:
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> test_replay_state_matches
        >>> # Example 2
        >>> test_replay_state_matches
    """
    storage = _storage()
    tool_registry = ToolRegistry()
    tool_registry.register(CountingTool())

    steps = [StepDefinition(step_id="echo", step_type="tool", tool_name="tools.counting", raw_input={"message": "x"})]
    executor = Executor(steps, storage, None, _memory_manager(), tool_registry)
    run = executor.run("wf", {"issue": "x"})

    replayer = RunReplayer(storage=storage, printer=lambda _: None)
    result = replayer.replay(run.run_id, verify_state=True)

    assert result.final_state == storage.load_latest_state(run.run_id)


def test_replay_does_not_call_tools() -> None:
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> test_replay_does_not_call_tools
        >>> # Example 2
        >>> test_replay_does_not_call_tools
    """
    storage = _storage()
    tool_registry = ToolRegistry()
    tool = CountingTool()
    tool_registry.register(tool)

    steps = [StepDefinition(step_id="echo", step_type="tool", tool_name="tools.counting", raw_input={"message": "x"})]
    executor = Executor(steps, storage, None, _memory_manager(), tool_registry)
    run = executor.run("wf", {"issue": "x"})
    before = tool.calls

    replayer = RunReplayer(storage=storage, printer=lambda _: None)
    replayer.replay(run.run_id)

    assert tool.calls == before


def test_replay_step_limit() -> None:
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> test_replay_step_limit
        >>> # Example 2
        >>> test_replay_step_limit
    """
    storage = _storage()
    tool_registry = ToolRegistry()
    tool_registry.register(CountingTool())

    def model_step(state: Dict[str, Any]) -> Dict[str, Any]:
        """Auto-generated documentation for this callable.
        
        Describes purpose, expected inputs/outputs, and behavior in this module.
        
        Example:
            >>> # Example 1
            >>> model_step
            >>> # Example 2
            >>> model_step
        """
        return {"summary": "ok"}

    steps = [
        StepDefinition(step_id="summarize", step_type="model", handler=model_step),
        StepDefinition(step_id="echo", step_type="tool", tool_name="tools.counting", raw_input={"message": "x"}),
    ]
    executor = Executor(steps, storage, None, _memory_manager(), tool_registry)
    run = executor.run("wf", {"issue": "x"})

    replayer = RunReplayer(storage=storage, printer=lambda _: None)
    result = replayer.replay(run.run_id, until="summarize")

    assert result.steps_replayed == 1


def test_replay_running_run_errors() -> None:
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> test_replay_running_run_errors
        >>> # Example 2
        >>> test_replay_running_run_errors
    """
    storage = _storage()
    from agent_runtime.core import Run, RunState
    run = Run(
        run_id="run_running",
        workflow_id="wf",
        workflow_version=None,
        workflow_hash=None,
        workflow_yaml=None,
        workflow_steps=None,
        input_hash=None,
        status="RUNNING",
        created_at="2026-01-01T00:00:00+00:00",
        state=RunState(_data={"inputs": {}, "steps": {}}),
    )
    storage.create_run(run)

    replayer = RunReplayer(storage=storage, printer=lambda _: None)
    with pytest.raises(ReplayDataMissingError):
        replayer.replay("run_running")
