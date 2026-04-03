from __future__ import annotations

"""File: tests/test_branch_resume.py

Purpose:
Ensure resume-point detection preserves failed branch path semantics.
"""


from agent_runtime.core import Executor
from agent_runtime.tools.registry import ToolRegistry
from agent_runtime.tools.base import ToolResult, RuntimeContext
from agent_runtime.workflow import load_workflow_from_text
from agent_runtime.resume import determine_resume_step
from conftest import make_storage, make_memory_manager, functions_dir


class FlakyTool:
    name = "tools.echo"
    description = "echo"
    input_schema = {"type": "object", "properties": {}}
    timeout = None
    retries = None

    async def execute(self, input, context: RuntimeContext) -> ToolResult:
        """Function implementation."""
        raise ValueError("fail")


def test_resume_after_branch_follows_same_path() -> None:
    """Function implementation."""
    yaml_text = """
schema_version: v1
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

    storage = make_storage()
    tool_registry = ToolRegistry()
    tool_registry.register(FlakyTool())

    executor = Executor(wf["steps"], storage, None, make_memory_manager(), tool_registry)
    run = executor.run(wf["workflow_id"], {"issue": "bug"})
    assert run.status == "FAILED"

    steps = storage.load_steps(run.run_id)
    resume_step = determine_resume_step(wf["steps"], steps)
    assert resume_step == "bug_path"
