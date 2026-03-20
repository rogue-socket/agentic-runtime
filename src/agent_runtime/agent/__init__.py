"""Agent subsystem — definition, registry, execution, and prompts.

Two data models coexist in this package:

* **AgentDefinition** (``definition.py``) — the *execution* model.  Describes
  how an agent works: LLM config, pipeline steps, strategy, and tools.
  Used by ``type: agent`` workflow steps and the ``AgentExecutor``.
  **This is the canonical model going forward.**

* **AgentManifest** (``manifest.py``) — the *packaging* model.  Describes
  what files an agent bundles for distribution: workflow path, handler
  files, tool files, environment variables.  Used by ``ai export`` /
  ``ai import`` and ``ai run <agent_id>`` resolution.
  **Deprecated**: packaging fields will be merged into AgentDefinition
  in a future release.  Prefer AgentDefinition for new agent YAML files.
"""

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

# Deprecated packaging model — will be removed in Phase 5.
# Prefer AgentDefinition for new agent definitions.
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
