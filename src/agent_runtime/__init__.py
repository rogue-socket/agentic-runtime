"""File: src/agent_runtime/__init__.py

Purpose:
Expose the package's primary public API in one import location.

Description:
Re-exports execution, workflow loading, replay, and state primitives so
consumers can import core runtime symbols without deep module paths.

Key Components:
- `Executor`, `Run`, `StepDefinition`, `StepExecution`
- Workflow/replay helpers and runtime state wrapper

Dependencies:
- Internal modules under `agent_runtime.*`

Inputs/Outputs:
- Input: import operations from application/test code
- Output: stable top-level symbols via `__all__`

Side Effects:
- Imports module dependencies at package import time.
"""

# TODO(sdk): Design and document a clean programmatic API surface for embedding
#   the runtime in applications. Target experience:
#     from agentic_runtime import Executor, run_workflow
#     result = run_workflow("my_agent@v1", inputs={"issue": "..."})
#   This should handle config loading, storage setup, and tool registration
#   internally so callers don't need to wire 5 objects together.

from __future__ import annotations

import asyncio
import os
from typing import Any, Callable, Dict, List, Optional

from .core import Executor, EventCallback, Run, RunState, StepDefinition, StepExecution, StepStatus
from .config import RuntimeConfig, load_config, apply_cli_overrides
from .errors import WorkflowIntegrityError
from .agent import AgentDefinition, AgentRegistry, AgentExecutor, load_agent_definition
from .llm import LLMRegistry, LLMProvider, ModelConfig, LLMClient, LLMResponse
from .workflow import load_workflow
from .replay import RunReplayer, ReplayResult
from .state import RuntimeState
from .storage import SQLiteStorage
from .memory import MemoryManager, WorkingMemory, EpisodicMemory, SemanticMemory, ProceduralMemory
from .tools import ToolRegistry
from .tools.echo import EchoTool
from .tools.http import HttpTool
from .tools.file import FileTool
from .tools.shell import ShellTool
from .tools.discovery import register_discovered_tools
from .logging import StructuredLogger
from .llm.handler import make_llm_handler
from .utils import sha256_json


def run_workflow(
    workflow_path: str,
    inputs: Optional[Dict[str, Any]] = None,
    *,
    config_path: str = "runtime.yaml",
    on_error: str = "fail_fast",
    on_event: Optional[EventCallback] = None,
) -> Run:
    """Run a workflow file with minimal setup.

    Handles config loading, storage, memory, tool registration, and executor
    construction internally.  This is the simplest way to execute a workflow
    programmatically.

    Args:
        workflow_path: Path to a workflow YAML file.
        inputs: Input key-value pairs for the workflow.
        config_path: Path to ``runtime.yaml`` (default: current directory).
        on_error: Error policy — ``"fail_fast"`` or ``"continue"``.
        on_event: Optional lifecycle event callback.

    Returns:
        The completed :class:`Run` object.

    Raises:
        RuntimeError: If called from within an already-running event loop.
            Use :func:`run_workflow_async` instead.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass  # No running loop — safe to proceed.
    else:
        raise RuntimeError(
            "Detected a running event loop. "
            "Use `run_workflow_async()` instead of `run_workflow()`."
        )
    return asyncio.run(run_workflow_async(
        workflow_path,
        inputs=inputs,
        config_path=config_path,
        on_error=on_error,
        on_event=on_event,
    ))


async def run_workflow_async(
    workflow_path: str,
    inputs: Optional[Dict[str, Any]] = None,
    *,
    config_path: str = "runtime.yaml",
    on_error: str = "fail_fast",
    on_event: Optional[EventCallback] = None,
) -> Run:
    """Async version of :func:`run_workflow`.

    Safe to ``await`` from FastAPI, Jupyter, or any async context.
    """
    cfg = load_config(config_path)

    # Build subsystems
    logger = StructuredLogger()
    storage = SQLiteStorage(cfg.db_path)
    memory_manager = MemoryManager(
        working=WorkingMemory(
            max_entries=cfg.working_memory_max_entries,
            max_scratch_bytes=cfg.working_memory_max_scratch_bytes,
        ),
        episodic=EpisodicMemory(db_path=cfg.db_path),
        semantic=SemanticMemory(db_path=cfg.db_path),
        procedural=ProceduralMemory(),
    )
    tool_registry = ToolRegistry()
    tool_registry.register(EchoTool())
    tool_registry.register(HttpTool())
    tool_registry.register(FileTool())
    tool_registry.register(ShellTool(
        allowlist=cfg.shell_allowlist or None,
        denylist=cfg.shell_denylist or None,
    ))
    register_discovered_tools(tool_registry, cfg.tools_dir)

    # Build agent registry and LLM client
    llm_client = LLMClient(registry=cfg.llm_registry, logger=logger)
    agent_registry = AgentRegistry()
    agents_dir = getattr(cfg, "agents_dir", "agents")
    if os.path.isdir(agents_dir):
        agent_registry = AgentRegistry.from_directory(agents_dir)
    functions_dir = getattr(cfg, "functions_dir", "functions")
    functions_dir = functions_dir if os.path.isdir(functions_dir) else None

    # Load and parse workflow
    workflow = load_workflow(workflow_path, functions_dir=functions_dir)

    input_state = inputs or {}

    executor = Executor(
        steps=workflow["steps"],
        storage=storage,
        logger=logger,
        memory_manager=memory_manager,
        tool_registry=tool_registry,
        overwrite_policy=cfg.overwrite_policy,
        on_event=on_event,
        agent_registry=agent_registry,
        llm_client=llm_client,
    )

    return await executor.run_async(
        workflow_id=workflow["workflow_id"],
        initial_state=input_state,
        workflow_version=workflow.get("workflow_version"),
        on_error=on_error,
        workflow_hash=workflow.get("workflow_hash"),
        workflow_yaml=workflow.get("workflow_yaml"),
        workflow_steps=workflow.get("workflow_steps"),
        input_hash=sha256_json(input_state),
    )

__all__ = [
    "Executor",
    "EventCallback",
    "Run",
    "RunState",
    "StepDefinition",
    "StepExecution",
    "StepStatus",
    "RuntimeConfig",
    "load_config",
    "apply_cli_overrides",
    "load_workflow",
    "RunReplayer",
    "ReplayResult",
    "RuntimeState",
    "WorkflowIntegrityError",
    "LLMRegistry",
    "LLMProvider",
    "ModelConfig",
    "LLMClient",
    "LLMResponse",
    "AgentDefinition",
    "AgentRegistry",
    "AgentExecutor",
    "load_agent_definition",
    "run_workflow",
    "run_workflow_async",
]
