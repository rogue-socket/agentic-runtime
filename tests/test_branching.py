from __future__ import annotations

"""File: tests/test_branching.py

Purpose:
Validate branch-rule workflow parsing and branch-path execution behavior.
"""

import pytest

from agent_runtime.core import Executor
from agent_runtime.errors import WorkflowValidationError
from agent_runtime.tools.registry import ToolRegistry
from agent_runtime.tools.base import ToolResult, RuntimeContext
from agent_runtime.workflow import load_workflow_from_text
from conftest import make_storage, make_memory_manager, functions_dir


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
schema_version: 2
workflow:
  id: triage
  version: v1
steps:
  - id: classify
    type: function
    function: stubs.generate_summary
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
    wf = load_workflow_from_text(yaml_text, functions_dir=functions_dir())

    tool_registry = ToolRegistry()
    tool_registry.register(EchoTool())

    executor = Executor(wf["steps"], make_storage(), None, make_memory_manager(), tool_registry)
    run = executor.run(wf["workflow_id"], {"issue": "bug"})
    assert "bug_path" in run.state.data["steps"]


def test_branch_default_path() -> None:
    yaml_text = """
schema_version: 2
workflow:
  id: triage
  version: v1
steps:
  - id: classify
    type: function
    function: stubs.generate_summary
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
    wf = load_workflow_from_text(yaml_text, functions_dir=functions_dir())

    tool_registry = ToolRegistry()
    tool_registry.register(EchoTool())

    executor = Executor(wf["steps"], make_storage(), None, make_memory_manager(), tool_registry)
    run = executor.run(wf["workflow_id"], {"issue": "feature"})
    assert "end" in run.state.data["steps"]


def test_invalid_branch_target() -> None:
    yaml_text = """
schema_version: 2
workflow:
  id: triage
  version: v1
steps:
  - id: classify
    type: function
    function: stubs.generate_summary
    inputs:
      issue: inputs.issue
    next:
      - when: state.inputs.issue == \"bug\"
        goto: missing
"""
    with pytest.raises(WorkflowValidationError):
        load_workflow_from_text(yaml_text, functions_dir=functions_dir())
