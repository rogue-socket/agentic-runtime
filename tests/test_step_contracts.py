from __future__ import annotations

import tempfile

import pytest

from agent_runtime.core import Executor, StepDefinition
from agent_runtime.errors import StepExecutionError, WorkflowValidationError
from agent_runtime.memory.base import MemoryManager
from agent_runtime.memory.episodic import EpisodicMemory
from agent_runtime.memory.procedural import ProceduralMemory
from agent_runtime.memory.semantic import SemanticMemory
from agent_runtime.memory.working import WorkingMemory
from agent_runtime.steps import StepHandlerRegistry
from agent_runtime.storage.sqlite import SQLiteStorage
from agent_runtime.tools.registry import ToolRegistry
from agent_runtime.workflow import load_workflow_from_text


def _memory_manager() -> MemoryManager:
    return MemoryManager(
        working=WorkingMemory(),
        episodic=EpisodicMemory(),
        semantic=SemanticMemory(),
        procedural=ProceduralMemory(),
    )


def _storage() -> SQLiteStorage:
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.close()
    return SQLiteStorage(tmp.name)


def test_contract_future_read_rejected() -> None:
    raw = """
name: contracts
inputs_contract: [issue]
steps:
  - id: classify
    type: model
    handler: step_classify
    inputs: [summary]
    outputs: [category]
  - id: summarize
    type: model
    handler: step_summarize
    inputs: [issue]
    outputs: [summary]
"""
    reg = StepHandlerRegistry()
    reg.register("step_classify", lambda s: {"category": "bug"})
    reg.register("step_summarize", lambda s: {"summary": "x"})
    with pytest.raises(WorkflowValidationError):
        load_workflow_from_text(raw, reg)


def test_contract_output_collision_rejected() -> None:
    raw = """
name: contracts
inputs_contract: [issue]
steps:
  - id: s1
    type: model
    handler: step_one
    inputs: [issue]
    outputs: [summary]
  - id: s2
    type: model
    handler: step_two
    inputs: [issue]
    outputs: [summary]
"""
    reg = StepHandlerRegistry()
    reg.register("step_one", lambda s: {"summary": "a"})
    reg.register("step_two", lambda s: {"summary": "b"})
    with pytest.raises(WorkflowValidationError):
        load_workflow_from_text(raw, reg)


def test_runtime_output_contract_enforced() -> None:
    storage = _storage()
    tool_registry = ToolRegistry()

    def bad_handler(state):
        return {"wrong": "x"}

    steps = [
        StepDefinition(
            step_id="bad_step",
            step_type="model",
            handler=bad_handler,
            input_spec={"issue": "inputs.issue"},
            output_contract=["summary"],
        )
    ]

    executor = Executor(steps, storage, None, _memory_manager(), tool_registry)
    run = executor.run("wf", {"issue": "x"})
    assert run.status == "FAILED"
    assert "Output contract violation" in (run.error or "")


def test_contract_inputs_list_maps_correctly() -> None:
    raw = """
name: contracts
inputs_contract: [issue]
steps:
  - id: summarize
    type: model
    handler: step_summarize
    inputs: [issue]
    outputs: [summary]
"""
    reg = StepHandlerRegistry()

    def summarize(state):
        return {"summary": f"sum:{state.get('issue')}"}

    reg.register("step_summarize", summarize)
    wf = load_workflow_from_text(raw, reg)

    storage = _storage()
    executor = Executor(wf["steps"], storage, None, _memory_manager(), ToolRegistry())
    run = executor.run("wf", {"issue": "hello"})
    assert run.status == "COMPLETED"
    assert run.state.data["steps"]["summarize"]["summary"] == "sum:hello"
