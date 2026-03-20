"""Agent subsystem — definition, registry, execution, and prompts."""

# Canonical agent system (execution)
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
]
