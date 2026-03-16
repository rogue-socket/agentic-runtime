"""Agent manifest loader and data model.

An agent manifest (``agent.yaml``) is the portable unit of the runtime.
It declares everything an agent needs to run: workflow, handlers, tools,
LLM providers, and environment variables.

Example ``agent.yaml``::

    agent:
      id: triage_agent
      version: v2
      description: "Triages incoming issues by severity and routes them"
      runtime: ">=0.1"

    # The workflow this agent executes
    # TODO: Support multiple workflows with a designated entry point
    workflow: workflows/triage.yaml

    # Handler files this agent needs
    handlers:
      - handlers/classify.py
      - handlers/summarize.py

    # Tool files this agent needs
    tools:
      - tools/github_tool.py

    # LLM providers this agent requires (must be configured in runtime.yaml)
    providers:
      - name: openai
        models: [gpt-4o-mini, gpt-4]

    # Environment variables that must be set
    env:
      - GITHUB_TOKEN

    # Default inputs (can be overridden at run time via -i)
    defaults:
      issue: "unspecified"
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List

import yaml

from ..errors import AgentValidationError


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ProviderRequirement:
    """An LLM provider + models the agent depends on."""
    name: str
    models: List[str] = field(default_factory=list)


@dataclass
class AgentManifest:
    """Parsed agent manifest."""

    # Identity
    agent_id: str
    version: str
    description: str = ""
    runtime_constraint: str = ""

    # Paths (relative to the project root)
    workflow: str = ""
    handlers: List[str] = field(default_factory=list)
    tools: List[str] = field(default_factory=list)

    # Requirements
    providers: List[ProviderRequirement] = field(default_factory=list)
    env: List[str] = field(default_factory=list)

    # Defaults
    defaults: Dict[str, Any] = field(default_factory=dict)

    # Where the manifest was loaded from (set by loader)
    manifest_path: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "agent": {
                "id": self.agent_id,
                "version": self.version,
            },
            "workflow": self.workflow,
        }
        if self.description:
            d["agent"]["description"] = self.description
        if self.runtime_constraint:
            d["agent"]["runtime"] = self.runtime_constraint
        if self.handlers:
            d["handlers"] = list(self.handlers)
        if self.tools:
            d["tools"] = list(self.tools)
        if self.providers:
            d["providers"] = [
                {"name": p.name, "models": list(p.models)} for p in self.providers
            ]
        if self.env:
            d["env"] = list(self.env)
        if self.defaults:
            d["defaults"] = dict(self.defaults)
        return d

    def to_yaml(self) -> str:
        return yaml.dump(self.to_dict(), default_flow_style=False, sort_keys=False)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_agent_manifest(path: str) -> AgentManifest:
    """Parse an ``agent.yaml`` file into an :class:`AgentManifest`."""
    if not os.path.isfile(path):
        raise AgentValidationError(f"Agent manifest not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise AgentValidationError("Agent manifest must be a YAML mapping.")

    # --- agent identity ---
    agent_block = raw.get("agent")
    if not isinstance(agent_block, dict):
        raise AgentValidationError("Manifest must contain an 'agent' mapping.")
    agent_id = agent_block.get("id")
    if not isinstance(agent_id, str) or not agent_id.strip():
        raise AgentValidationError("agent.id must be a non-empty string.")
    version = agent_block.get("version")
    if not isinstance(version, str) or not version.strip():
        raise AgentValidationError("agent.version must be a non-empty string.")

    # --- workflow ---
    workflow = raw.get("workflow", "")
    if not isinstance(workflow, str) or not workflow.strip():
        raise AgentValidationError("Manifest must declare a 'workflow' path.")

    # --- handlers ---
    handlers_raw = raw.get("handlers", [])
    if not isinstance(handlers_raw, list):
        raise AgentValidationError("handlers must be a list of file paths.")
    handlers = [str(h) for h in handlers_raw]

    # --- tools ---
    tools_raw = raw.get("tools", [])
    if not isinstance(tools_raw, list):
        raise AgentValidationError("tools must be a list of file paths.")
    tools = [str(t) for t in tools_raw]

    # --- providers ---
    providers_raw = raw.get("providers", [])
    if not isinstance(providers_raw, list):
        raise AgentValidationError("providers must be a list.")
    providers: List[ProviderRequirement] = []
    for p in providers_raw:
        if isinstance(p, str):
            providers.append(ProviderRequirement(name=p))
        elif isinstance(p, dict):
            name = p.get("name", "")
            if not name:
                raise AgentValidationError("Each provider must have a 'name'.")
            models = p.get("models", [])
            if not isinstance(models, list):
                raise AgentValidationError(f"Provider '{name}' models must be a list.")
            providers.append(ProviderRequirement(name=name, models=[str(m) for m in models]))
        else:
            raise AgentValidationError("Each provider entry must be a string or mapping.")

    # --- env ---
    env_raw = raw.get("env", [])
    if not isinstance(env_raw, list):
        raise AgentValidationError("env must be a list of environment variable names.")
    env = [str(e) for e in env_raw]

    # --- defaults ---
    defaults = raw.get("defaults", {})
    if not isinstance(defaults, dict):
        raise AgentValidationError("defaults must be a mapping.")

    return AgentManifest(
        agent_id=agent_id,
        version=version,
        description=agent_block.get("description", ""),
        runtime_constraint=str(agent_block.get("runtime", "")),
        workflow=workflow,
        handlers=handlers,
        tools=tools,
        providers=providers,
        env=env,
        defaults=defaults,
        manifest_path=os.path.abspath(path),
    )


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """One check performed during agent validation."""
    category: str          # e.g. "workflow", "handler", "tool", "provider", "env"
    name: str              # e.g. file path, provider name, env var
    ok: bool
    message: str = ""


def validate_agent(
    manifest: AgentManifest,
    project_root: str = ".",
    llm_registry: Any = None,
) -> List[ValidationResult]:
    """Run pre-flight checks against the manifest.

    Returns a list of :class:`ValidationResult` items — one per check.
    The caller decides what to do with failures (print, abort, etc.).
    """
    results: List[ValidationResult] = []

    # --- workflow file ---
    wf_path = os.path.join(project_root, manifest.workflow)
    if os.path.isfile(wf_path):
        results.append(ValidationResult("workflow", manifest.workflow, True))
    else:
        results.append(ValidationResult(
            "workflow", manifest.workflow, False,
            f"file not found: {wf_path}",
        ))

    # --- handler files ---
    for h in manifest.handlers:
        h_path = os.path.join(project_root, h)
        if os.path.isfile(h_path):
            results.append(ValidationResult("handler", h, True))
        else:
            results.append(ValidationResult(
                "handler", h, False,
                f"file not found: {h_path}",
            ))

    # --- tool files ---
    for t in manifest.tools:
        t_path = os.path.join(project_root, t)
        if os.path.isfile(t_path):
            results.append(ValidationResult("tool", t, True))
        else:
            results.append(ValidationResult(
                "tool", t, False,
                f"file not found: {t_path}",
            ))

    # --- LLM providers ---
    for prov in manifest.providers:
        if llm_registry is None:
            results.append(ValidationResult(
                "provider", prov.name, False,
                "no LLM registry configured in runtime.yaml",
            ))
            continue
        provider_obj = llm_registry.get_provider(prov.name)
        if provider_obj is None:
            results.append(ValidationResult(
                "provider", prov.name, False,
                f"provider '{prov.name}' not configured in runtime.yaml",
            ))
            continue
        # Provider exists — check credentials
        if not provider_obj.has_credentials():
            results.append(ValidationResult(
                "provider", prov.name, False,
                f"API key env var '{provider_obj.api_key_env}' is not set",
            ))
            continue
        # Check models
        missing_models = [
            m for m in prov.models if provider_obj.get_model(m) is None
        ]
        if missing_models:
            results.append(ValidationResult(
                "provider", prov.name, False,
                f"models not configured: {', '.join(missing_models)}",
            ))
        else:
            results.append(ValidationResult("provider", prov.name, True))

    # --- environment variables ---
    for var in manifest.env:
        if os.environ.get(var):
            results.append(ValidationResult("env", var, True))
        else:
            results.append(ValidationResult(
                "env", var, False,
                f"environment variable '{var}' is not set",
            ))

    return results
