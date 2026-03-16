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

from .core import Executor, Run, RunState, StepDefinition, StepExecution, StepStatus
from .steps import StepHandlerRegistry, generate_summary, classify_severity, diagnose_issue, propose_fix, review_code
from .handler_discovery import discover_handlers, register_discovered_handlers
from .config import RuntimeConfig, load_config, apply_cli_overrides
from .errors import WorkflowIntegrityError
from .agent import AgentManifest, load_agent_manifest, validate_agent
from .llm import LLMRegistry, LLMProvider, ModelConfig
from .workflow import load_workflow
from .replay import RunReplayer, ReplayResult
from .state import RuntimeState

__all__ = [
    "Executor",
    "Run",
    "RunState",
    "StepDefinition",
    "StepExecution",
    "StepStatus",
    "StepHandlerRegistry",
    "generate_summary",
    "classify_severity",
    "diagnose_issue",
    "propose_fix",
    "review_code",
    "discover_handlers",
    "register_discovered_handlers",
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
    "AgentManifest",
    "load_agent_manifest",
    "validate_agent",
]
