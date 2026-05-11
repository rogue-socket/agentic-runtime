"""ForrestRun — embeddable workflow engine for AI agents.

Quick start::

    from agent_runtime import RuntimeBuilder

    with RuntimeBuilder().with_db_path(":memory:").build() as runtime:
        run = runtime.run("workflows/example.yaml", inputs={...})
        print(run.outputs)

Or for the simplest case::

    from agent_runtime import run_workflow
    result = run_workflow("workflows/example.yaml", inputs={...})
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from ._async_compat import run_coro_blocking
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
from .utils import sha256_json

# SDK surface — builder, runtime, factory functions, typed events
from .builder import RuntimeBuilder, Runtime
from .defaults import default_tool_registry, default_memory_manager, default_llm_client, default_agent_registry
from .events import (
    Event, RunStartEvent, StepStartEvent, StepCompleteEvent,
    StepErrorEvent, RunCompleteEvent, TypedEventCallback, adapt_typed_callback,
)


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

    Note:
        Safe to call from inside a running event loop (FastAPI, Jupyter) —
        the workflow is dispatched to a worker thread with its own loop.
        For native async usage prefer :func:`run_workflow_async`.
    """
    return run_coro_blocking(run_workflow_async(
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
        episodic=EpisodicMemory(
            db_path=cfg.db_path,
            max_summary_bytes=cfg.episodic_max_summary_bytes,
        ),
        semantic=SemanticMemory(db_path=cfg.db_path),
        procedural=ProceduralMemory(db_path=cfg.db_path),
    )
    try:
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
        llm_client = LLMClient(
            registry=cfg.llm_registry,
            logger=logger,
            rate_limit_rpm=cfg.llm_rate_limit_rpm,
            max_requests_per_run=cfg.llm_max_requests_per_run,
            max_total_tokens_per_run=cfg.llm_max_total_tokens_per_run,
            max_cost_usd_per_run=cfg.llm_max_cost_usd_per_run,
            pricing_usd_per_1k_tokens=cfg.llm_pricing_usd_per_1k_tokens,
        )
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
            default_model=cfg.default_model,
        )

        return await executor.run_async(
            workflow_id=workflow["workflow_id"],
            initial_state=input_state,
            workflow_inputs=workflow.get("inputs", {}),
            workflow_version=workflow.get("workflow_version"),
            on_error=on_error,
            workflow_hash=workflow.get("workflow_hash"),
            workflow_yaml=workflow.get("workflow_yaml"),
            workflow_steps=workflow.get("workflow_steps"),
            input_hash=sha256_json(input_state),
        )
    finally:
        storage.close()

__all__ = [
    # SDK surface — primary
    "RuntimeBuilder",
    "Runtime",
    "run_workflow",
    "run_workflow_async",
    # Factory functions
    "default_tool_registry",
    "default_memory_manager",
    "default_llm_client",
    "default_agent_registry",
    # Typed events
    "Event",
    "RunStartEvent",
    "StepStartEvent",
    "StepCompleteEvent",
    "StepErrorEvent",
    "RunCompleteEvent",
    "TypedEventCallback",
    "adapt_typed_callback",
    # Core types
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
    # LLM
    "LLMRegistry",
    "LLMProvider",
    "ModelConfig",
    "LLMClient",
    "LLMResponse",
    # Agent
    "AgentDefinition",
    "AgentRegistry",
    "AgentExecutor",
    "load_agent_definition",
]
