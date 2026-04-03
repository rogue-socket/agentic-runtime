from __future__ import annotations

"""File: tests/test_step_contracts.py

Purpose:
Validate workflow contract parsing and runtime output enforcement rules.
"""


import pytest

from agent_runtime.core import Executor, StepDefinition
from agent_runtime.errors import StepExecutionError, WorkflowValidationError
from agent_runtime.tools.registry import ToolRegistry
from agent_runtime.workflow import load_workflow_from_text
from conftest import make_storage, make_memory_manager, functions_dir


def test_contract_future_read_rejected() -> None:
    """Function implementation."""
    raw = """
schema_version: v1
workflow:
    id: contracts
    version: v1
inputs: [issue]
steps:
  - id: classify
    type: function
    function: stubs.classify_severity
    inputs: [summary]
    outputs: [category]
  - id: summarize
    type: function
    function: stubs.generate_summary
    inputs: [issue]
    outputs: [summary]
"""
    with pytest.raises(WorkflowValidationError):
        load_workflow_from_text(raw, functions_dir=functions_dir())


def test_contract_output_collision_rejected() -> None:
    """Function implementation."""
    raw = """
schema_version: v1
workflow:
    id: contracts
    version: v1
inputs: [issue]
steps:
  - id: s1
    type: function
    function: stubs.generate_summary
    inputs: [issue]
    outputs: [summary]
  - id: s2
    type: function
    function: stubs.generate_summary
    inputs: [issue]
    outputs: [summary]
"""
    with pytest.raises(WorkflowValidationError):
        load_workflow_from_text(raw, functions_dir=functions_dir())


def test_runtime_output_contract_enforced() -> None:
    """Function implementation."""
    storage = make_storage()
    tool_registry = ToolRegistry()

    def bad_function(inputs):
        """Function implementation."""
        return {"wrong": "x"}

    steps = [
        StepDefinition(
            step_id="bad_step",
            step_type="function",
            function_callable=bad_function,
            input_spec={"issue": "inputs.issue"},
            output_contract=["summary"],
        )
    ]

    executor = Executor(steps, storage, None, make_memory_manager(), tool_registry)
    run = executor.run("wf", {"issue": "x"})
    assert run.status == "FAILED"
    assert "Output contract violation" in (run.error or "")


def test_contract_inputs_list_maps_correctly() -> None:
    """Function implementation."""
    raw = """
schema_version: v1
workflow:
    id: contracts
    version: v1
inputs: [issue]
steps:
  - id: summarize
    type: function
    function: stubs.generate_summary
    inputs: [issue]
    outputs: [summary]
"""
    wf = load_workflow_from_text(raw, functions_dir=functions_dir())

    storage = make_storage()
    executor = Executor(wf["steps"], storage, None, make_memory_manager(), ToolRegistry())
    run = executor.run("wf", {"issue": "hello"})
    assert run.status == "COMPLETED"
    assert run.state.data["steps"]["summarize"]["summary"] == "Summary of issue: hello"
