"""Agent subsystem — definition, registry, execution, and prompts."""

# New agent system
from .definition import AgentDefinition, PipelineStep, StrategyConfig, load_agent_definition
from .executor import AgentExecutor
from .prompts import PromptEntry, PromptRegistry
from .registry import AgentRegistry
from .strategies import (
    AgentContext,
    AgentResult,
    AgentTurn,
    ToolCall,
    SingleCallStrategy,
    ReActStrategy,
    resolve_strategy,
)

# Legacy exports (kept during transition — will be removed in Phase 5)
from .manifest import AgentManifest, load_agent_manifest, validate_agent, ValidationResult
from .packaging import export_agent, import_agent

__all__ = [
    # new agent system
    "AgentDefinition",
    "PipelineStep",
    "StrategyConfig",
    "load_agent_definition",
    "AgentExecutor",
    "AgentRegistry",
    "AgentContext",
    "AgentResult",
    "AgentTurn",
    "ToolCall",
    "PromptEntry",
    "PromptRegistry",
    "SingleCallStrategy",
    "ReActStrategy",
    "resolve_strategy",
    # legacy
    "AgentManifest",
    "load_agent_manifest",
    "validate_agent",
    "ValidationResult",
    "export_agent",
    "import_agent",
]
