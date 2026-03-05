from __future__ import annotations

import pytest

from agent_runtime.core import Executor
from agent_runtime.errors import WorkflowValidationError
from agent_runtime.memory.base import MemoryManager
from agent_runtime.memory.episodic import EpisodicMemory
from agent_runtime.memory.procedural import ProceduralMemory
from agent_runtime.memory.semantic import SemanticMemory
from agent_runtime.memory.working import WorkingMemory
from agent_runtime.storage.sqlite import SQLiteStorage
from agent_runtime.steps import StepHandlerRegistry, generate_summary
from agent_runtime.tools.registry import ToolRegistry
from agent_runtime.tools.base import ToolResult, RuntimeContext
from agent_runtime.workflow import load_workflow_from_text


def _memory_manager() -> MemoryManager:
    return MemoryManager(
        working=WorkingMemory(),
        episodic=EpisodicMemory(),
        semantic=SemanticMemory(),
        procedural=ProceduralMemory(),
    )


def _storage() -> SQLiteStorage:
    import tempfile
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.close()
    return SQLiteStorage(tmp.name)


class EchoTool:
    name = "tools.echo"
    description = "echo"
    input_schema = {"type": "object", "properties": {}}
    timeout = None
    retries = None

    async def execute(self, input: dict, context: RuntimeContext) -> ToolResult:
        return ToolResult(success=True, output={"ok": True}, error=None, metadata=None)


def test_branch_bug_path() -> None:
    yaml_text = """
name: triage
steps:
  - id: classify
    type: model
    handler: generate_summary
    inputs:
      issue: inputs.issue
    next:
      - when: state.inputs.issue == \"bug\"
        goto: bug_path
      - default: end
  - id: bug_path
    type: tool
    tool: tools.echo
  - id: end
    type: tool
    tool: tools.echo
"""
    reg = StepHandlerRegistry()
    reg.register("generate_summary", generate_summary)
    wf = load_workflow_from_text(yaml_text, reg)

    tool_registry = ToolRegistry()
    tool_registry.register(EchoTool())

    executor = Executor(wf["steps"], _storage(), None, _memory_manager(), tool_registry)
    run = executor.run(wf["name"], {"issue": "bug"})
    assert "bug_path" in run.state.data["steps"]


def test_branch_default_path() -> None:
    yaml_text = """
name: triage
steps:
  - id: classify
    type: model
    handler: generate_summary
    inputs:
      issue: inputs.issue
    next:
      - when: state.inputs.issue == \"bug\"
        goto: bug_path
      - default: end
  - id: bug_path
    type: tool
    tool: tools.echo
  - id: end
    type: tool
    tool: tools.echo
"""
    reg = StepHandlerRegistry()
    reg.register("generate_summary", generate_summary)
    wf = load_workflow_from_text(yaml_text, reg)

    tool_registry = ToolRegistry()
    tool_registry.register(EchoTool())

    executor = Executor(wf["steps"], _storage(), None, _memory_manager(), tool_registry)
    run = executor.run(wf["name"], {"issue": "feature"})
    assert "end" in run.state.data["steps"]


def test_invalid_branch_target() -> None:
    yaml_text = """
name: triage
steps:
  - id: classify
    type: model
    handler: generate_summary
    inputs:
      issue: inputs.issue
    next:
      - when: state.inputs.issue == \"bug\"
        goto: missing
"""
    reg = StepHandlerRegistry()
    reg.register("generate_summary", generate_summary)
    with pytest.raises(WorkflowValidationError):
        load_workflow_from_text(yaml_text, reg)
