from __future__ import annotations

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
    def __init__(self) -> None:
        self.read_calls = 0
        self.write_calls = 0

    def read(self, context: Dict[str, Any]) -> Dict[str, Any]:
        self.read_calls += 1
        return {}

    def write(self, payload: Dict[str, Any]) -> None:
        self.write_calls += 1


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


def test_model_step_success() -> None:
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

    steps = [StepDefinition(step_id="echo", step_type="tool", tool_name="tools.echo", raw_input={"x": 1})]
    executor = Executor(steps, storage, None, _memory_manager(), tool_registry)

    run = executor.run("wf", {"issue": "x"})
    assert run.status == StepStatus.COMPLETED
    assert run.state.data["steps"]["echo"]["x"] == 1


def test_workflow_yaml_validation(tmp_path) -> None:
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("name: x\nsteps: {}\n", encoding="utf-8")

    registry = StepHandlerRegistry()
    registry.register("generate_summary", generate_summary)

    with pytest.raises(WorkflowValidationError):
        load_workflow(str(bad_yaml), registry)


def test_state_versioning() -> None:
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
    storage = _storage()
    tool_registry = ToolRegistry()
    logger = None

    attempts = {"count": 0}

    def flaky_handler(state: Dict[str, Any]) -> Dict[str, Any]:
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
