"""Agent definition — the data model for an agent (LLM + tools + strategy).

An agent is defined as a YAML file with identity, model config, a system
prompt (inline or from the prompt registry), a list of tools, a reasoning
strategy (single / react / custom), and a pipeline of internal steps.

Every agent must declare a ``pipeline`` — an ordered sequence of model
and tool steps that defines the agent's internal execution structure.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml

from ..errors import AgentValidationError
from .prompts import PromptEntry, PromptRegistry

# -- strategy config -------------------------------------------------------

VALID_STRATEGIES = ("single", "react", "custom")


@dataclass
class StrategyConfig:
    """How the agent reasons: single LLM call, ReAct loop, or custom."""

    type: str = "single"
    max_iterations: int = 10
    stop_conditions: List[str] = field(default_factory=list)
    custom_handler: Optional[str] = None  # module.ClassName for custom

    def __post_init__(self) -> None:
        if self.type not in VALID_STRATEGIES:
            raise AgentValidationError(
                f"Invalid strategy type '{self.type}'. "
                f"Must be one of {VALID_STRATEGIES}"
            )
        if self.type == "custom" and not self.custom_handler:
            raise AgentValidationError(
                "Strategy type 'custom' requires 'custom_handler' field"
            )


# -- pipeline step ---------------------------------------------------------

VALID_PIPELINE_STEP_TYPES = ("model", "tool")
# TODO(roadmap): Consider adding "agent" pipeline step type for nested agent calls
# in the future.  For now, pipelines only support model + tool steps.


@dataclass
class PipelineStep:
    """One step inside an agent's internal pipeline.

    * ``model`` steps make an LLM call.  They inherit the agent-level
      ``model`` and ``system`` unless overridden on the step itself.
      A ``prompt`` is required on every model step.

    * ``tool`` steps call a tool directly.  The tool must appear in the
      agent's top-level ``tools`` allowlist.
    """

    id: str
    type: str  # "model" | "tool"

    # model step fields
    prompt: str = ""           # required for type=model (template with {{ }})
    model: Optional[str] = None   # overrides agent.model for this step
    system: Optional[str] = None  # overrides agent.system for this step

    # tool step fields
    tool: Optional[str] = None    # required for type=tool
    inputs: Optional[Dict[str, Any]] = None  # bare dot-paths for tool inputs

    def __post_init__(self) -> None:
        if self.type not in VALID_PIPELINE_STEP_TYPES:
            raise AgentValidationError(
                f"Invalid pipeline step type '{self.type}'. "
                f"Must be one of {VALID_PIPELINE_STEP_TYPES}"
            )
        if self.type == "model" and not self.prompt:
            raise AgentValidationError(
                f"Pipeline model step '{self.id}' requires a 'prompt' field"
            )
        if self.type == "tool" and not self.tool:
            raise AgentValidationError(
                f"Pipeline tool step '{self.id}' requires a 'tool' field"
            )


# -- agent definition ------------------------------------------------------


@dataclass
class AgentDefinition:
    """A complete agent definition: identity + LLM config + tools + strategy + pipeline."""

    agent_id: str
    version: str
    model: str = ""  # resolved from runtime config when empty
    description: str = ""

    # System prompt — inline text OR a prompt-registry reference ("prompts.xyz@v2")
    system: str = ""

    # Internal execution pipeline (mandatory — even a simple agent has one model step)
    pipeline: List[PipelineStep] = field(default_factory=list)

    # Tools this agent is allowed to use (allowlist for pipeline tool steps)
    tools: List[str] = field(default_factory=list)

    # Reasoning strategy
    strategy: StrategyConfig = field(default_factory=StrategyConfig)

    # Auto-inject tool-calling instructions into system prompts for react agents
    auto_tool_prompt: bool = True

    # Output key name for plain-text LLM responses (default "text")
    output_key: str = "text"

    # LLM params
    temperature: float = 0.2
    max_tokens: int = 4096
    params: Dict[str, Any] = field(default_factory=dict)

    # Per-agent prompt registry (each agent owns its own prompts)
    prompt_registry: PromptRegistry = field(default_factory=PromptRegistry)

    # Source path (set by loader)
    definition_path: str = ""

    def __post_init__(self) -> None:
        # Validate that all tool steps reference tools in the allowlist
        for step in self.pipeline:
            if step.type == "tool" and step.tool and step.tool not in self.tools:
                raise AgentValidationError(
                    f"Pipeline tool step '{step.id}' references '{step.tool}' "
                    f"which is not in the agent's tools list: {self.tools}"
                )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize back to a YAML-compatible dict."""
        pipeline_data = []
        for step in self.pipeline:
            entry: Dict[str, Any] = {"id": step.id, "type": step.type}
            if step.type == "model":
                entry["prompt"] = step.prompt
                if step.model:
                    entry["model"] = step.model
                if step.system:
                    entry["system"] = step.system
            elif step.type == "tool":
                entry["tool"] = step.tool
                if step.inputs:
                    entry["inputs"] = step.inputs
            pipeline_data.append(entry)

        result: Dict[str, Any] = {
            "agent": {
                "id": self.agent_id,
                "version": self.version,
                "description": self.description,
                **({"model": self.model} if self.model else {}),
                "system": self.system,
                "tools": self.tools,
                "pipeline": pipeline_data,
                "strategy": {
                    "type": self.strategy.type,
                    "max_iterations": self.strategy.max_iterations,
                    "stop_conditions": self.strategy.stop_conditions,
                },
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "output_key": self.output_key,
            }
        }
        if self.strategy.custom_handler:
            result["agent"]["strategy"]["custom_handler"] = self.strategy.custom_handler
        if self.params:
            result["agent"]["params"] = self.params
        return result


# -- loader ----------------------------------------------------------------


def load_agent_definition(path: str) -> AgentDefinition:
    """Load an agent definition from a YAML file."""
    if not os.path.isfile(path):
        raise AgentValidationError(f"Agent definition not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict) or "agent" not in raw:
        raise AgentValidationError(f"{path}: missing top-level 'agent' key")
    return _parse_agent(raw["agent"], path, raw)


def _parse_agent(data: dict, path: str, raw: Optional[dict] = None) -> AgentDefinition:
    """Parse the ``agent:`` block into an AgentDefinition."""
    for key in ("id", "version"):
        if key not in data:
            raise AgentValidationError(
                f"{path}: agent missing required field '{key}'"
            )

    strategy = _parse_strategy(data.get("strategy", {}), path)
    prompt_registry = _parse_prompts(data, path, raw)
    tools = _parse_list(data.get("tools", []), "tools", path)
    pipeline = _parse_pipeline(data.get("pipeline", []), path)

    if not pipeline:
        raise AgentValidationError(
            f"{path}: agent must define a 'pipeline' with at least one step"
        )

    return AgentDefinition(
        agent_id=data["id"],
        version=str(data["version"]),
        model=data.get("model", ""),
        description=data.get("description", ""),
        system=data.get("system", ""),
        pipeline=pipeline,
        tools=tools,
        strategy=strategy,
        auto_tool_prompt=data.get("auto_tool_prompt", True),
        output_key=data.get("output_key", "text"),
        temperature=float(data.get("temperature", 0.2)),
        max_tokens=int(data.get("max_tokens", 4096)),
        params=data.get("params", {}),
        prompt_registry=prompt_registry,
        definition_path=os.path.abspath(path),
    )


def _parse_pipeline(data: Any, path: str) -> List[PipelineStep]:
    """Parse the ``pipeline:`` list into PipelineStep objects."""
    if not data:
        return []
    if not isinstance(data, list):
        raise AgentValidationError(f"{path}: 'pipeline' must be a list")
    steps: List[PipelineStep] = []
    seen_ids: List[str] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise AgentValidationError(
                f"{path}: pipeline step {i} must be a mapping"
            )
        step_id = item.get("id")
        if not isinstance(step_id, str) or not step_id.strip():
            raise AgentValidationError(
                f"{path}: pipeline step {i} must have a string 'id'"
            )
        if step_id in seen_ids:
            raise AgentValidationError(
                f"{path}: duplicate pipeline step id: {step_id}"
            )
        seen_ids.append(step_id)
        step_type = item.get("type")
        if step_type not in VALID_PIPELINE_STEP_TYPES:
            raise AgentValidationError(
                f"{path}: pipeline step '{step_id}' has invalid type '{step_type}'. "
                f"Must be one of {VALID_PIPELINE_STEP_TYPES}"
            )
        steps.append(
            PipelineStep(
                id=step_id,
                type=step_type,
                prompt=item.get("prompt", ""),
                model=item.get("model"),
                system=item.get("system"),
                tool=item.get("tool"),
                inputs=item.get("inputs"),
            )
        )
    return steps


def _parse_strategy(data, path: str) -> StrategyConfig:
    if not data:
        return StrategyConfig()
    if isinstance(data, str):
        return StrategyConfig(type=data)
    if not isinstance(data, dict):
        raise AgentValidationError(
            f"{path}: 'strategy' must be a string or mapping"
        )
    return StrategyConfig(
        type=data.get("type", "single"),
        max_iterations=int(data.get("max_iterations", 10)),
        stop_conditions=data.get("stop_conditions", []),
        custom_handler=data.get("custom_handler"),
    )


def _parse_prompts(
    data: dict, path: str, raw: Optional[dict] = None
) -> PromptRegistry:
    """Build a per-agent PromptRegistry from the agent YAML.

    Supports three sources (all optional, combined):

    1. **Inline in agent block** — ``agent.prompts:`` list of entries.
    2. **File reference** — ``agent.prompts_file: path/to/prompts.yaml``
       (resolved relative to the agent YAML file).
    3. **Top-level prompts block** — ``prompts:`` at the YAML root
       (sibling to ``agent:``).
    """
    registry = PromptRegistry()
    agent_dir = os.path.dirname(os.path.abspath(path))

    # source 1: inline prompts inside agent block
    inline = data.get("prompts")
    if isinstance(inline, list):
        for item in inline:
            _register_prompt_item(registry, item, path)

    # source 2: file reference
    prompts_file = data.get("prompts_file")
    if prompts_file:
        abs_path = (
            prompts_file
            if os.path.isabs(prompts_file)
            else os.path.join(agent_dir, prompts_file)
        )
        if os.path.isfile(abs_path):
            # only load the specific file, not the whole directory
            from .prompts import _load_prompt_file
            for entry in _load_prompt_file(abs_path):
                registry.register(entry)
        elif os.path.isdir(abs_path):
            file_reg = PromptRegistry.from_directory(abs_path)
            for entries in file_reg._prompts.values():
                for entry in entries.values():
                    registry.register(entry)

    # source 3: top-level prompts block in YAML (sibling to agent:)
    if raw and "prompts" in raw:
        top_prompts = raw["prompts"]
        if isinstance(top_prompts, list):
            for item in top_prompts:
                _register_prompt_item(registry, item, path)

    return registry


def _register_prompt_item(
    registry: PromptRegistry, item: dict, path: str
) -> None:
    """Register a single inline prompt entry into a registry."""
    if not isinstance(item, dict):
        raise AgentValidationError(f"{path}: each prompt must be a mapping")
    for key in ("id", "text"):
        if key not in item:
            raise AgentValidationError(
                f"{path}: prompt missing required field '{key}'"
            )
    registry.register(
        PromptEntry(
            prompt_id=item["id"],
            version=str(item.get("version", "v1")),
            text=item["text"],
            description=item.get("description", ""),
        )
    )


def _parse_list(value, field_name: str, path: str) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [value]
    raise AgentValidationError(
        f"{path}: '{field_name}' must be a list or string"
    )
