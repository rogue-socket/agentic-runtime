from __future__ import annotations

"""File: tests/test_retry_policy.py

Purpose:
Test retry policy semantics across successful and exhausted attempts.
"""

from pathlib import Path
from typing import Any, Dict

import pytest

from agent_runtime.core import Executor, RetryPolicy, StepDefinition, StepStatus
from agent_runtime.tools.registry import ToolRegistry
from agent_runtime.workflow import load_workflow
from conftest import make_storage, make_memory_manager


def test_retry_success_attempt_count() -> None:
    storage = make_storage()
    tool_registry = ToolRegistry()

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
            input_spec={"issue": "inputs.issue"},
            retry=RetryPolicy(attempts=2, backoff="fixed", initial_delay=0),
        )
    ]

    executor = Executor(steps, storage, None, make_memory_manager(), tool_registry)
    run = executor.run("wf", {"issue": "x"})
    assert run.status == StepStatus.COMPLETED

    execs = storage.load_steps(run.run_id)
    assert execs[-1].attempt_count == 2


def test_retry_exhaustion_marks_failed() -> None:
    storage = make_storage()
    tool_registry = ToolRegistry()

    def always_fail(inputs: Dict[str, Any]) -> Dict[str, Any]:
        raise ValueError("fail")

    steps = [
        StepDefinition(
            step_id="failer",
            step_type="function",
            function_callable=always_fail,
            input_spec={"issue": "inputs.issue"},
            retry=RetryPolicy(attempts=3, backoff="fixed", initial_delay=0),
        )
    ]

    executor = Executor(steps, storage, None, make_memory_manager(), tool_registry)
    run = executor.run("wf", {"issue": "x"})
    assert run.status == StepStatus.FAILED

    execs = storage.load_steps(run.run_id)
    assert execs[-1].attempt_count == 3


def test_no_retry_defaults_to_one_attempt() -> None:
    storage = make_storage()
    tool_registry = ToolRegistry()

    def ok(inputs: Dict[str, Any]) -> Dict[str, Any]:
        return {"ok": True}

    steps = [StepDefinition(step_id="ok", step_type="function", function_callable=ok, input_spec={"issue": "inputs.issue"})]
    executor = Executor(steps, storage, None, make_memory_manager(), tool_registry)
    run = executor.run("wf", {"issue": "x"})

    execs = storage.load_steps(run.run_id)
    assert execs[-1].attempt_count == 1


def test_workflow_retry_validation(tmp_path) -> None:
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text(
        "name: wf\nsteps:\n  - id: a\n    type: function\n    function: stubs.generate_summary\n    retry:\n      attempts: 0\n",
        encoding="utf-8",
    )

    functions_dir = str(Path(__file__).resolve().parents[1] / "functions")

    with pytest.raises(Exception):
        load_workflow(str(bad_yaml), functions_dir=functions_dir)
