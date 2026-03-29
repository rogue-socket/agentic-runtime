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
from typing import Any, Dict

import pytest

from agent_runtime.core import Executor, RetryPolicy, StepDefinition, StepStatus
from agent_runtime.errors import WorkflowValidationError
from agent_runtime.memory.base import MemoryManager
from agent_runtime.tools.registry import ToolRegistry
from agent_runtime.tools.base import ToolResult, RuntimeContext
from agent_runtime.workflow import load_workflow
from conftest import make_storage, make_memory_manager


def generate_summary(inputs: Dict[str, Any]) -> Dict[str, Any]:
    issue = inputs.get("issue", "")
    if not issue:
        raise KeyError("Missing required key: issue")
    return {"summary": f"Issue related to {issue}."}


class CounterMemory:
    def __init__(self) -> None:
        self.read_calls = 0
        self.write_calls = 0

    def read(self, context: Dict[str, Any]) -> Dict[str, Any]:
        self.read_calls += 1
        return {}

    def write(self, payload: Dict[str, Any]) -> None:
        self.write_calls += 1


def test_function_step_success() -> None:
    storage = make_storage()
    tool_registry = ToolRegistry()
    logger = None

    steps = [
        StepDefinition(
            step_id="generate_summary",
            step_type="function",
            function_callable=generate_summary,
            input_spec={"issue": "inputs.issue"},
        )
    ]
    executor = Executor(steps, storage, logger, make_memory_manager(), tool_registry)

    run = executor.run("wf", {"issue": "Login API fails for invalid token"})
    assert run.status == StepStatus.COMPLETED
    assert "generate_summary" in run.state.data["steps"]
    assert "summary" in run.state.data["steps"]["generate_summary"]


def test_function_step_missing_issue() -> None:
    storage = make_storage()
    tool_registry = ToolRegistry()
    logger = None

    steps = [
        StepDefinition(
            step_id="generate_summary",
            step_type="function",
            function_callable=generate_summary,
            input_spec={"issue": "inputs.issue"},
        )
    ]
    executor = Executor(steps, storage, logger, make_memory_manager(), tool_registry)

    run = executor.run("wf", {})
    assert run.status == StepStatus.FAILED
    assert run.error is not None


def test_run_applies_workflow_input_defaults_when_provided() -> None:
    storage = make_storage()
    tool_registry = ToolRegistry()

    def read_priority(inputs: Dict[str, Any]) -> Dict[str, Any]:
        return {"priority": inputs["priority"]}

    steps = [
        StepDefinition(
            step_id="read_priority",
            step_type="function",
            function_callable=read_priority,
            input_spec={"priority": "inputs.priority"},
        )
    ]
    executor = Executor(steps, storage, None, make_memory_manager(), tool_registry)

    run = executor.run(
        "wf",
        {"issue": "x"},
        workflow_inputs={
            "priority": {"required": False, "default": "low"},
        },
    )
    assert run.status == StepStatus.COMPLETED
    assert run.state.data["inputs"]["priority"] == "low"
    assert run.state.data["steps"]["read_priority"]["priority"] == "low"


def test_run_default_does_not_override_explicit_input() -> None:
    storage = make_storage()
    tool_registry = ToolRegistry()

    def read_priority(inputs: Dict[str, Any]) -> Dict[str, Any]:
        return {"priority": inputs["priority"]}

    steps = [
        StepDefinition(
            step_id="read_priority",
            step_type="function",
            function_callable=read_priority,
            input_spec={"priority": "inputs.priority"},
        )
    ]
    executor = Executor(steps, storage, None, make_memory_manager(), tool_registry)

    run = executor.run(
        "wf",
        {"priority": "high"},
        workflow_inputs={
            "priority": {"required": False, "default": "low"},
        },
    )
    assert run.status == StepStatus.COMPLETED
    assert run.state.data["inputs"]["priority"] == "high"
    assert run.state.data["steps"]["read_priority"]["priority"] == "high"


def test_tool_step_success() -> None:
    storage = make_storage()
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
    executor = Executor(steps, storage, None, make_memory_manager(), tool_registry)

    run = executor.run("wf", {"issue": "x"})
    assert run.status == StepStatus.COMPLETED
    assert run.state.data["steps"]["echo"]["x"] == 1


def test_run_async_executes_tool_step() -> None:
    """Ensure async execution path runs tool steps successfully."""
    storage = make_storage()
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
    executor = Executor(steps, storage, None, make_memory_manager(), tool_registry)

    async def _run() -> None:
        run = await executor.run_async("wf", {"issue": "x"})
        assert run.status == StepStatus.COMPLETED
        assert run.state.data["steps"]["echo"]["x"] == 2

    asyncio.run(_run())


def test_run_raises_inside_event_loop() -> None:
    """Sync run should refuse to execute inside a running event loop."""
    storage = make_storage()
    tool_registry = ToolRegistry()
    steps = [
        StepDefinition(
            step_id="generate_summary",
            step_type="function",
            function_callable=generate_summary,
            input_spec={"issue": "inputs.issue"},
        )
    ]
    executor = Executor(steps, storage, None, make_memory_manager(), tool_registry)

    async def _run() -> None:
        with pytest.raises(RuntimeError):
            executor.run("wf", {"issue": "Login API fails for invalid token"})

    asyncio.run(_run())


def test_workflow_yaml_validation(tmp_path) -> None:
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("name: x\nsteps: {}\n", encoding="utf-8")

    with pytest.raises(WorkflowValidationError):
        load_workflow(str(bad_yaml))


def test_state_versioning() -> None:
    storage = make_storage()
    tool_registry = ToolRegistry()

    steps = [
        StepDefinition(
            step_id="generate_summary",
            step_type="function",
            function_callable=generate_summary,
            input_spec={"issue": "inputs.issue"},
        )
    ]
    executor = Executor(steps, storage, None, make_memory_manager(), tool_registry)

    run = executor.run("wf", {"issue": "Login API fails for invalid token"})
    assert run.status == StepStatus.COMPLETED

    conn = sqlite3.connect(storage.db_path)
    count = conn.execute("SELECT COUNT(*) FROM state_versions WHERE run_id = ?", (run.run_id,)).fetchone()[0]
    conn.close()

    assert count == 2


def test_memory_hooks_invoked() -> None:
    storage = make_storage()
    tool_registry = ToolRegistry()

    working = CounterMemory()
    episodic = CounterMemory()
    semantic = CounterMemory()
    procedural = CounterMemory()
    memory_manager = MemoryManager(working, episodic, semantic, procedural)

    steps = [
        StepDefinition(
            step_id="generate_summary",
            step_type="function",
            function_callable=generate_summary,
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
    # 1 write per step + 1 final write at run completion for episodic recording
    assert working.write_calls == 2
    assert episodic.write_calls == 2
    assert semantic.write_calls == 2
    assert procedural.write_calls == 2


def test_retry_policy_succeeds() -> None:
    storage = make_storage()
    tool_registry = ToolRegistry()
    logger = None

    attempts = {"count": 0}

    def flaky_function(inputs: Dict[str, Any]) -> Dict[str, Any]:
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise ValueError("transient")
        return {"ok": True}

    steps = [
        StepDefinition(
            step_id="flaky",
            step_type="function",
            function_callable=flaky_function,
            retry=RetryPolicy(attempts=2, backoff="fixed", initial_delay=0),
        )
    ]
    executor = Executor(steps, storage, logger, make_memory_manager(), tool_registry)

    run = executor.run("wf", {"issue": "x"})
    assert run.status == StepStatus.COMPLETED
    assert run.state.data["steps"]["flaky"]["ok"] is True


def test_retry_emits_step_retry_event() -> None:
    storage = make_storage()
    tool_registry = ToolRegistry()
    events = []

    attempts = {"count": 0}

    def flaky_function(inputs: Dict[str, Any]) -> Dict[str, Any]:
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise ValueError("transient")
        return {"ok": True}

    steps = [
        StepDefinition(
            step_id="flaky",
            step_type="function",
            function_callable=flaky_function,
            retry=RetryPolicy(attempts=2, backoff="fixed", initial_delay=0),
        )
    ]

    def on_event(event: str, payload: Dict[str, Any]) -> None:
        events.append((event, payload))

    executor = Executor(
        steps,
        storage,
        None,
        make_memory_manager(),
        tool_registry,
        on_event=on_event,
    )

    run = executor.run("wf", {"issue": "x"})
    assert run.status == StepStatus.COMPLETED

    retry_events = [payload for event, payload in events if event == "STEP_RETRY"]
    assert len(retry_events) == 1
    assert retry_events[0]["attempt"] == 1
    assert retry_events[0]["next_attempt"] == 2
    assert retry_events[0]["max_attempts"] == 2


def test_optional_step_uses_default_output_and_continues() -> None:
    storage = make_storage()
    tool_registry = ToolRegistry()

    def enrich_fails(inputs: Dict[str, Any]) -> Dict[str, Any]:
        raise ValueError("enrichment backend unavailable")

    def consume_summary(inputs: Dict[str, Any]) -> Dict[str, Any]:
        return {"final": f"used={inputs['summary']}"}

    steps = [
        StepDefinition(
            step_id="enrich",
            step_type="function",
            function_callable=enrich_fails,
            output_contract=["summary"],
            optional=True,
            default_output={"summary": "fallback"},
        ),
        StepDefinition(
            step_id="consume",
            step_type="function",
            function_callable=consume_summary,
            input_spec={"summary": "steps.enrich.summary"},
        ),
    ]

    executor = Executor(steps, storage, None, make_memory_manager(), tool_registry)
    run = executor.run("wf", {"issue": "x"})

    assert run.status == StepStatus.COMPLETED
    assert run.state.data["steps"]["enrich"]["summary"] == "fallback"
    assert run.state.data["steps"]["consume"]["final"] == "used=fallback"

    persisted_steps = storage.load_steps(run.run_id)
    enrich_exec = next(step for step in persisted_steps if step.step_id == "enrich")
    assert enrich_exec.status == StepStatus.COMPLETED
    assert enrich_exec.last_error is not None
    assert "ValueError" in enrich_exec.last_error


def test_heartbeat_emitted_for_long_running_tool_step() -> None:
    storage = make_storage()
    tool_registry = ToolRegistry()
    events = []

    class SlowTool:
        name = "tools.slow"
        description = "slow"
        input_schema = {"type": "object", "properties": {}}
        timeout = None
        retries = None

        async def execute(self, input: Dict[str, Any], context: RuntimeContext) -> ToolResult:
            await asyncio.sleep(0.08)
            return ToolResult(success=True, output={"ok": True}, error=None, metadata=None)

    tool_registry.register(SlowTool())

    steps = [StepDefinition(step_id="slow", step_type="tool", tool_name="tools.slow", raw_input={})]

    def on_event(event: str, payload: Dict[str, Any]) -> None:
        events.append((event, payload))

    executor = Executor(
        steps,
        storage,
        None,
        make_memory_manager(),
        tool_registry,
        on_event=on_event,
        heartbeat_interval_s=0.005,
    )

    run = executor.run("wf", {"issue": "x"})
    assert run.status == StepStatus.COMPLETED

    heartbeat_events = [payload for event, payload in events if event == "STEP_HEARTBEAT"]
    assert heartbeat_events

    progress_events = [payload for event, payload in events if event == "STEP_PROGRESS"]
    assert progress_events
    phases = {payload.get("phase") for payload in progress_events}
    assert "dispatch" in phases
    assert "heartbeat" in phases
    assert "complete" in phases


def test_tool_step_timeout_retries_and_fails_cleanly() -> None:
    storage = make_storage()
    tool_registry = ToolRegistry()

    class SlowTool:
        name = "tools.slow"
        description = "slow"
        input_schema = {"type": "object", "properties": {}}
        timeout = None
        retries = None

        async def execute(self, input: Dict[str, Any], context: RuntimeContext) -> ToolResult:
            await asyncio.sleep(0.08)
            return ToolResult(success=True, output={"ok": True}, error=None, metadata=None)

    tool_registry.register(SlowTool())

    steps = [
        StepDefinition(
            step_id="slow",
            step_type="tool",
            tool_name="tools.slow",
            raw_input={},
            timeout_ms=10,
            retry=RetryPolicy(attempts=2, backoff="fixed", initial_delay=0),
        )
    ]
    executor = Executor(steps, storage, None, make_memory_manager(), tool_registry)

    run = executor.run("wf", {"issue": "x"})
    assert run.status == StepStatus.FAILED
    assert run.error is not None
    assert "timed out" in run.error

    persisted = storage.load_steps(run.run_id)
    assert len(persisted) == 1
    assert persisted[0].attempt_count == 2
    assert persisted[0].last_error is not None
    assert "timed out" in persisted[0].last_error


def test_event_callback_failure_is_non_fatal() -> None:
    storage = make_storage()
    tool_registry = ToolRegistry()

    def ok(inputs: Dict[str, Any]) -> Dict[str, Any]:
        return {"ok": True}

    def on_event(event: str, payload: Dict[str, Any]) -> None:
        raise RuntimeError("observer unavailable")

    steps = [
        StepDefinition(
            step_id="ok",
            step_type="function",
            function_callable=ok,
        )
    ]
    executor = Executor(
        steps,
        storage,
        None,
        make_memory_manager(),
        tool_registry,
        on_event=on_event,
    )

    run = executor.run("wf", {"issue": "x"})
    assert run.status == StepStatus.COMPLETED
    assert run.state.data["steps"]["ok"]["ok"] is True


def test_storage_append_failure_marks_run_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = make_storage()
    tool_registry = ToolRegistry()
    captured_run_id: Dict[str, str] = {}

    def ok(inputs: Dict[str, Any]) -> Dict[str, Any]:
        return {"ok": True}

    original_create_run = storage.create_run

    def track_create_run(run) -> None:
        captured_run_id["id"] = run.run_id
        original_create_run(run)

    monkeypatch.setattr(storage, "create_run", track_create_run)

    failure_once = {"raised": False}

    def fail_append_step(run_id: str, step) -> None:
        if not failure_once["raised"]:
            failure_once["raised"] = True
            raise RuntimeError("append write failed")

    monkeypatch.setattr(storage, "append_step", fail_append_step)

    steps = [StepDefinition(step_id="ok", step_type="function", function_callable=ok)]
    executor = Executor(steps, storage, None, make_memory_manager(), tool_registry)

    with pytest.raises(RuntimeError, match="append write failed"):
        executor.run("wf", {"issue": "x"})

    persisted = storage.load_run(captured_run_id["id"])
    assert persisted.status == StepStatus.FAILED
    assert persisted.error is not None
    assert "append write failed" in persisted.error
    assert persisted.completed_at is not None


def test_original_error_is_preserved_when_status_persist_also_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = make_storage()
    tool_registry = ToolRegistry()

    def ok(inputs: Dict[str, Any]) -> Dict[str, Any]:
        return {"ok": True}

    def fail_append_step(run_id: str, step) -> None:
        raise RuntimeError("append write failed")

    def fail_update_run_status(
        run_id: str,
        status: str,
        error: str | None,
        started_at: str | None = None,
        completed_at: str | None = None,
    ) -> None:
        raise RuntimeError("status persist failed")

    monkeypatch.setattr(storage, "append_step", fail_append_step)
    monkeypatch.setattr(storage, "update_run_status", fail_update_run_status)

    steps = [StepDefinition(step_id="ok", step_type="function", function_callable=ok)]
    executor = Executor(steps, storage, None, make_memory_manager(), tool_registry)

    with pytest.raises(RuntimeError, match="append write failed"):
        executor.run("wf", {"issue": "x"})


def test_on_error_continue_completes_with_errors() -> None:
    storage = make_storage()
    tool_registry = ToolRegistry()

    def fail_step(inputs: Dict[str, Any]) -> Dict[str, Any]:
        raise ValueError("boom")

    def success_step(inputs: Dict[str, Any]) -> Dict[str, Any]:
        return {"ok": True}

    steps = [
        StepDefinition(step_id="fail", step_type="function", function_callable=fail_step),
        StepDefinition(step_id="succeed", step_type="function", function_callable=success_step),
    ]
    executor = Executor(steps, storage, None, make_memory_manager(), tool_registry)

    run = executor.run("wf", {"issue": "x"}, on_error="continue")
    assert run.status == StepStatus.COMPLETED_WITH_ERRORS
    assert run.state.data["steps"]["succeed"]["ok"] is True

    persisted = storage.load_steps(run.run_id)
    assert [step.status for step in persisted] == [StepStatus.FAILED, StepStatus.COMPLETED]


def test_state_snapshots_persisted() -> None:
    storage = make_storage()
    tool_registry = ToolRegistry()

    steps = [
        StepDefinition(
            step_id="generate_summary",
            step_type="function",
            function_callable=generate_summary,
            input_spec={"issue": "inputs.issue"},
        )
    ]
    executor = Executor(steps, storage, None, make_memory_manager(), tool_registry)

    run = executor.run("wf", {"issue": "Login API fails for invalid token"})
    assert run.status == StepStatus.COMPLETED

    execs = storage.load_steps(run.run_id)
    assert execs[0].state_before is not None
    assert execs[0].state_after is not None
