from __future__ import annotations

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


def test_retry_success_attempt_count() -> None:
    storage = _storage()
    tool_registry = ToolRegistry()

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
    storage = _storage()
    tool_registry = ToolRegistry()

    def always_fail(state: Dict[str, Any]) -> Dict[str, Any]:
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
    storage = _storage()
    tool_registry = ToolRegistry()

    def ok(state: Dict[str, Any]) -> Dict[str, Any]:
        return {"ok": True}

    steps = [StepDefinition(step_id="ok", step_type="model", handler=ok, input_spec={"issue": "inputs.issue"})]
    executor = Executor(steps, storage, None, _memory_manager(), tool_registry)
    run = executor.run("wf", {"issue": "x"})

    execs = storage.load_steps(run.run_id)
    assert execs[-1].attempt_count == 1


def test_workflow_retry_validation(tmp_path) -> None:
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
