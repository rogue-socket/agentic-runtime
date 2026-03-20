# TODO(H3-high): This file contains 6 junk auto-generated docstrings
#   ("Auto-generated documentation for this callable") that should be replaced
#   with real descriptions or removed entirely. Found at lines 26, 45, 79, 93, 135, 177.
from __future__ import annotations

"""File: tests/test_branching.py

Purpose:
Validate branch-rule workflow parsing and branch-path execution behavior.
"""

import pytest
from pathlib import Path

from agent_runtime.core import Executor
from agent_runtime.errors import WorkflowValidationError
from agent_runtime.memory.base import MemoryManager
from agent_runtime.memory.episodic import EpisodicMemory
from agent_runtime.memory.procedural import ProceduralMemory
from agent_runtime.memory.semantic import SemanticMemory
from agent_runtime.memory.working import WorkingMemory
from agent_runtime.storage.sqlite import SQLiteStorage
from agent_runtime.tools.registry import ToolRegistry
from agent_runtime.tools.base import ToolResult, RuntimeContext
from agent_runtime.workflow import load_workflow_from_text


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


def _functions_dir() -> str:
    return str(Path(__file__).resolve().parents[1] / "functions")


class EchoTool:
    """Auto-generated documentation for this class.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> EchoTool
        >>> # Example 2
        >>> EchoTool
    """
    name = "tools.echo"
    description = "echo"
    input_schema = {"type": "object", "properties": {}}
    timeout = None
    retries = None

    async def execute(self, input: dict, context: RuntimeContext) -> ToolResult:
        """Auto-generated documentation for this callable.
        
        Describes purpose, expected inputs/outputs, and behavior in this module.
        
        Example:
            >>> # Example 1
            >>> execute
            >>> # Example 2
            >>> execute
        """
        return ToolResult(success=True, output={"ok": True}, error=None, metadata=None)


def test_branch_bug_path() -> None:
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> test_branch_bug_path
        >>> # Example 2
        >>> test_branch_bug_path
    """
    yaml_text = """
name: triage
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
    wf = load_workflow_from_text(yaml_text, functions_dir=_functions_dir())

    tool_registry = ToolRegistry()
    tool_registry.register(EchoTool())

    executor = Executor(wf["steps"], _storage(), None, _memory_manager(), tool_registry)
    run = executor.run(wf["workflow_id"], {"issue": "bug"})
    assert "bug_path" in run.state.data["steps"]


def test_branch_default_path() -> None:
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> test_branch_default_path
        >>> # Example 2
        >>> test_branch_default_path
    """
    yaml_text = """
name: triage
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
    wf = load_workflow_from_text(yaml_text, functions_dir=_functions_dir())

    tool_registry = ToolRegistry()
    tool_registry.register(EchoTool())

    executor = Executor(wf["steps"], _storage(), None, _memory_manager(), tool_registry)
    run = executor.run(wf["workflow_id"], {"issue": "feature"})
    assert "end" in run.state.data["steps"]


def test_invalid_branch_target() -> None:
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> test_invalid_branch_target
        >>> # Example 2
        >>> test_invalid_branch_target
    """
    yaml_text = """
name: triage
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
        load_workflow_from_text(yaml_text, functions_dir=_functions_dir())
