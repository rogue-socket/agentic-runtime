from __future__ import annotations

"""File: tests/test_branch_resume.py

Purpose:
Ensure resume-point detection preserves failed branch path semantics.
"""

from agent_runtime.core import Executor
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
from agent_runtime.resume import determine_resume_step


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


def _storage() -> SQLiteStorage:
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> _storage
        >>> # Example 2
        >>> _storage
    """
    import tempfile
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.close()
    return SQLiteStorage(tmp.name)


class FlakyTool:
    """Auto-generated documentation for this class.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> FlakyTool
        >>> # Example 2
        >>> FlakyTool
    """
    name = "tools.echo"
    description = "echo"
    input_schema = {"type": "object", "properties": {}}
    timeout = None
    retries = None

    async def execute(self, input, context: RuntimeContext) -> ToolResult:
        """Auto-generated documentation for this callable.
        
        Describes purpose, expected inputs/outputs, and behavior in this module.
        
        Example:
            >>> # Example 1
            >>> execute
            >>> # Example 2
            >>> execute
        """
        raise ValueError("fail")


def test_resume_after_branch_follows_same_path() -> None:
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> test_resume_after_branch_follows_same_path
        >>> # Example 2
        >>> test_resume_after_branch_follows_same_path
    """
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

    storage = _storage()
    tool_registry = ToolRegistry()
    tool_registry.register(FlakyTool())

    executor = Executor(wf["steps"], storage, None, _memory_manager(), tool_registry)
    run = executor.run(wf["name"], {"issue": "bug"})
    assert run.status == "FAILED"

    steps = storage.load_steps(run.run_id)
    resume_step = determine_resume_step(wf["steps"], steps)
    assert resume_step == "bug_path"
