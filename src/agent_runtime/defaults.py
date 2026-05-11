"""Public factory functions for building runtime components.

These provide sensible defaults for creating the subsystems that the
Executor requires.  SDK users can call them directly for customization,
or use :class:`RuntimeBuilder` for a fluent setup experience.
"""

from __future__ import annotations

import os
from typing import Optional

from .agent import AgentRegistry
from .config import RuntimeConfig
from .llm import LLMClient
from .logging import StructuredLogger
from .memory import EpisodicMemory, MemoryManager, ProceduralMemory, SemanticMemory, WorkingMemory
from .tools import ToolRegistry
from .tools.discovery import register_discovered_tools
from .tools.echo import EchoTool
from .tools.file import FileTool
from .tools.http import HttpTool
from .tools.shell import ShellTool


def default_tool_registry(
    tools_dir: str = "tools",
    shell_allowlist: Optional[list] = None,
    shell_denylist: Optional[list] = None,
) -> ToolRegistry:
    """Create a tool registry with built-in tools and discovered tools.

    Registers the four built-in tools (echo, http, file, shell) and then
    discovers any custom tool classes in *tools_dir*.
    """
    registry = ToolRegistry()

    registry.register(EchoTool())
    registry.register(HttpTool())
    registry.register(FileTool())
    registry.register(ShellTool(
        allowlist=shell_allowlist or None,
        denylist=shell_denylist or None,
    ))

    register_discovered_tools(registry, tools_dir)

    return registry


def default_memory_manager(
    db_path: str = "runtime.db",
    max_entries: int = 50,
    max_scratch_bytes: int = 256_000,
    episodic_max_summary_bytes: int = 512,
) -> MemoryManager:
    """Build a memory manager with all four tiers.

    Working memory is in-process.  Episodic, semantic, and procedural
    tiers are backed by the SQLite database at *db_path*.
    """
    return MemoryManager(
        working=WorkingMemory(max_entries=max_entries, max_scratch_bytes=max_scratch_bytes),
        episodic=EpisodicMemory(db_path=db_path, max_summary_bytes=episodic_max_summary_bytes),
        semantic=SemanticMemory(db_path=db_path),
        procedural=ProceduralMemory(db_path=db_path),
    )


def default_llm_client(
    cfg: RuntimeConfig,
    logger: Optional[StructuredLogger] = None,
) -> LLMClient:
    """Create an LLM client with rate limits and cost tracking from *cfg*."""
    return LLMClient(
        registry=cfg.llm_registry,
        logger=logger,
        rate_limit_rpm=cfg.llm_rate_limit_rpm,
        max_requests_per_run=cfg.llm_max_requests_per_run,
        max_total_tokens_per_run=cfg.llm_max_total_tokens_per_run,
        max_cost_usd_per_run=cfg.llm_max_cost_usd_per_run,
        pricing_usd_per_1k_tokens=cfg.llm_pricing_usd_per_1k_tokens,
    )


def default_agent_registry(agents_dir: str = "agents") -> AgentRegistry:
    """Build an agent registry by scanning the agents directory.

    Returns an empty registry if *agents_dir* does not exist.
    """
    if os.path.isdir(agents_dir):
        return AgentRegistry.from_directory(agents_dir)
    return AgentRegistry()
