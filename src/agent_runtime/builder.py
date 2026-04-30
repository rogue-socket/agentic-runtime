"""Fluent builder and reusable runtime for executing workflows.

Usage::

    from agent_runtime import RuntimeBuilder

    # Minimal — in-memory, no API keys needed for function/tool workflows
    with RuntimeBuilder().with_db_path(":memory:").build() as runtime:
        run = runtime.run("workflows/example.yaml", inputs={"key": "value"})
        print(run.outputs)

    # Configured — real LLM, custom tools directory
    runtime = (
        RuntimeBuilder()
        .with_config_path("runtime.yaml")
        .with_model("openai/gpt-4o")
        .build()
    )
    run = await runtime.run_async("workflows/research.yaml", inputs={"topic": "AI"})
    runtime.close()
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Callable, Dict, List, Optional, Union

from .config import RuntimeConfig, load_config
from .core import Executor, EventCallback, Run
from .defaults import (
    default_agent_registry,
    default_llm_client,
    default_memory_manager,
    default_tool_registry,
)
from .events import TypedEventCallback, adapt_typed_callback
from .logging import StructuredLogger
from .storage import SQLiteStorage
from .tools import ToolRegistry
from .utils import sha256_json
from .workflow import load_workflow, load_workflow_from_text


class Runtime:
    """A configured runtime that can execute workflows.

    Use :class:`RuntimeBuilder` to create instances.  Supports use as a
    context manager for automatic resource cleanup::

        with RuntimeBuilder().with_db_path(":memory:").build() as rt:
            run = rt.run(workflow_yaml_string, inputs={...})
    """

    def __init__(
        self,
        config: RuntimeConfig,
        storage: SQLiteStorage,
        memory_manager: Any,
        tool_registry: ToolRegistry,
        agent_registry: Any,
        llm_client: Any,
        logger: StructuredLogger,
        on_event: Optional[EventCallback] = None,
    ) -> None:
        self._config = config
        self._storage = storage
        self._memory_manager = memory_manager
        self._tool_registry = tool_registry
        self._agent_registry = agent_registry
        self._llm_client = llm_client
        self._logger = logger
        self._on_event = on_event
        self._closed = False

    def run(
        self,
        workflow: str,
        inputs: Optional[Dict[str, Any]] = None,
        *,
        on_error: str = "fail_fast",
        on_event: Optional[EventCallback] = None,
    ) -> Run:
        """Run a workflow synchronously.

        Args:
            workflow: File path to a YAML workflow **or** inline YAML string.
            inputs: Workflow input key-value pairs.
            on_error: ``"fail_fast"`` or ``"continue"``.
            on_event: Per-run event callback (overrides the builder default).

        Raises:
            RuntimeError: If called from within an already-running event loop.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError(
                "Detected a running event loop. Use `runtime.run_async()` instead."
            )
        return asyncio.run(self.run_async(workflow, inputs, on_error=on_error, on_event=on_event))

    async def run_async(
        self,
        workflow: str,
        inputs: Optional[Dict[str, Any]] = None,
        *,
        on_error: str = "fail_fast",
        on_event: Optional[EventCallback] = None,
    ) -> Run:
        """Run a workflow asynchronously.

        Safe to ``await`` from FastAPI, Jupyter, or any async context.
        """
        if self._closed:
            raise RuntimeError("Runtime is closed.")

        parsed = self._load_workflow(workflow)
        input_state = inputs or {}
        event_cb = on_event or self._on_event

        executor = Executor(
            steps=parsed["steps"],
            storage=self._storage,
            logger=self._logger,
            memory_manager=self._memory_manager,
            tool_registry=self._tool_registry,
            overwrite_policy=self._config.overwrite_policy,
            on_event=event_cb,
            agent_registry=self._agent_registry,
            llm_client=self._llm_client,
            default_model=self._config.default_model,
        )

        return await executor.run_async(
            workflow_id=parsed["workflow_id"],
            initial_state=input_state,
            workflow_inputs=parsed.get("inputs", {}),
            workflow_version=parsed.get("workflow_version"),
            on_error=on_error,
            workflow_hash=parsed.get("workflow_hash"),
            workflow_yaml=parsed.get("workflow_yaml"),
            workflow_steps=parsed.get("workflow_steps"),
            input_hash=sha256_json(input_state),
        )

    def _load_workflow(self, workflow: str) -> Dict[str, Any]:
        """Parse *workflow* as a file path or inline YAML string."""
        functions_dir = self._config.functions_dir
        if not os.path.isdir(functions_dir):
            functions_dir = None

        # Heuristic: if it looks like a file path, load from disk.
        if not _looks_like_yaml(workflow):
            return load_workflow(workflow, functions_dir=functions_dir)
        return load_workflow_from_text(workflow, functions_dir=functions_dir)

    def close(self) -> None:
        """Release storage and memory resources."""
        if not self._closed:
            self._closed = True
            self._storage.close()
            if hasattr(self._memory_manager, "close"):
                self._memory_manager.close()

    def __enter__(self) -> "Runtime":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    async def __aenter__(self) -> "Runtime":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        self.close()


def _looks_like_yaml(text: str) -> bool:
    """Return ``True`` if *text* appears to be inline YAML rather than a file path."""
    return "\n" in text or text.lstrip().startswith(("schema_version:", "workflow:"))


class RuntimeBuilder:
    """Fluent builder for creating a :class:`Runtime`.

    Example::

        runtime = (
            RuntimeBuilder()
            .with_model("openai/gpt-4o")
            .with_db_path(":memory:")
            .build()
        )
    """

    def __init__(self) -> None:
        self._config: Optional[RuntimeConfig] = None
        self._config_path: Optional[str] = None
        self._db_path: Optional[str] = None
        self._model: Optional[str] = None
        self._tools_dir: Optional[str] = None
        self._agents_dir: Optional[str] = None
        self._functions_dir: Optional[str] = None
        self._extra_tools: List[Any] = []
        self._on_event: Optional[EventCallback] = None
        self._shell_allowlist: Optional[list] = None
        self._shell_denylist: Optional[list] = None

    def with_config(self, config: RuntimeConfig) -> "RuntimeBuilder":
        """Use an explicit :class:`RuntimeConfig` object."""
        self._config = config
        return self

    def with_config_path(self, path: str) -> "RuntimeBuilder":
        """Load configuration from a ``runtime.yaml`` file."""
        self._config_path = path
        return self

    def with_model(self, model: str) -> "RuntimeBuilder":
        """Set the default LLM model (e.g. ``"openai/gpt-4o"``)."""
        self._model = model
        return self

    def with_db_path(self, path: str) -> "RuntimeBuilder":
        """Set the SQLite database path.  Use ``":memory:"`` for ephemeral runs."""
        self._db_path = path
        return self

    def with_tools_dir(self, path: str) -> "RuntimeBuilder":
        """Set the directory for custom tool discovery."""
        self._tools_dir = path
        return self

    def with_tool(self, tool: Any) -> "RuntimeBuilder":
        """Register an additional tool instance."""
        self._extra_tools.append(tool)
        return self

    def with_agents_dir(self, path: str) -> "RuntimeBuilder":
        """Set the directory for agent definition discovery."""
        self._agents_dir = path
        return self

    def with_functions_dir(self, path: str) -> "RuntimeBuilder":
        """Set the directory for Python function modules."""
        self._functions_dir = path
        return self

    def with_on_event(self, callback: Union[EventCallback, TypedEventCallback]) -> "RuntimeBuilder":
        """Set a lifecycle event callback.

        Accepts either a raw ``EventCallback(str, dict)`` or a typed
        ``TypedEventCallback(Event)`` — the builder auto-detects which
        based on the function's type hints.
        """
        self._on_event = callback  # type: ignore[assignment]
        return self

    def with_shell_allowlist(self, patterns: list) -> "RuntimeBuilder":
        """Set regex patterns for allowed shell commands."""
        self._shell_allowlist = patterns
        return self

    def with_shell_denylist(self, patterns: list) -> "RuntimeBuilder":
        """Set regex patterns for denied shell commands."""
        self._shell_denylist = patterns
        return self

    def build(self) -> Runtime:
        """Construct all runtime components and return a :class:`Runtime`."""
        # Resolve config
        if self._config is not None:
            cfg = self._config
        elif self._config_path is not None:
            cfg = load_config(self._config_path)
        else:
            cfg = RuntimeConfig()

        # Apply builder overrides
        if self._db_path is not None:
            cfg.db_path = self._db_path
        if self._model is not None:
            cfg.default_model = self._model
        if self._tools_dir is not None:
            cfg.tools_dir = self._tools_dir
        if self._agents_dir is not None:
            cfg.agents_dir = self._agents_dir
        if self._functions_dir is not None:
            cfg.functions_dir = self._functions_dir

        # Build subsystems
        logger = StructuredLogger()
        storage = SQLiteStorage(cfg.db_path)
        memory_manager = default_memory_manager(
            db_path=cfg.db_path,
            max_entries=cfg.working_memory_max_entries,
            max_scratch_bytes=cfg.working_memory_max_scratch_bytes,
        )
        tool_registry = default_tool_registry(
            tools_dir=cfg.tools_dir,
            shell_allowlist=self._shell_allowlist or cfg.shell_allowlist or None,
            shell_denylist=self._shell_denylist or cfg.shell_denylist or None,
        )
        for tool in self._extra_tools:
            tool_registry.register(tool)

        agent_registry = default_agent_registry(cfg.agents_dir)
        llm_client = default_llm_client(cfg, logger)

        # Resolve event callback
        on_event = self._on_event
        if on_event is not None:
            # Auto-detect typed callback: if the callback has type hints
            # that don't match (str, dict), assume it's a TypedEventCallback.
            hints = getattr(on_event, "__annotations__", {})
            params = list(hints.values())
            if params and params[0] is not str:
                on_event = adapt_typed_callback(on_event)

        return Runtime(
            config=cfg,
            storage=storage,
            memory_manager=memory_manager,
            tool_registry=tool_registry,
            agent_registry=agent_registry,
            llm_client=llm_client,
            logger=logger,
            on_event=on_event,
        )
