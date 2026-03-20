"""Agent executor — runs an agent definition through its reasoning strategy.

This is the bridge between the workflow executor (which hands off an
agent step) and the strategy implementations (which run the actual
LLM + tool reasoning loop via the agent's pipeline).
"""

from __future__ import annotations

import copy
from typing import Any, Dict, Optional

from ..llm.client import LLMClient
from ..tools.registry import ToolRegistry
from .definition import AgentDefinition
from .strategies import AgentContext, AgentResult, resolve_strategy


class AgentExecutor:
    """Executes an agent by resolving its prompts, picking a strategy,
    and running the reasoning loop through the agent's pipeline."""

    def __init__(
        self,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        logger: Any = None,
    ) -> None:
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.logger = logger

    async def execute(
        self,
        agent: AgentDefinition,
        inputs: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult:
        """Run the agent's reasoning strategy and return the result."""
        # resolve prompt-registry references to actual text
        resolved = self._resolve_prompts(agent)

        # pick the right strategy
        strategy = resolve_strategy(resolved.strategy)

        # run it
        return await strategy.run(
            agent=resolved,
            llm_client=self.llm_client,
            tool_registry=self.tool_registry,
            inputs=inputs,
            context=context,
        )

    def _resolve_prompts(self, agent: AgentDefinition) -> AgentDefinition:
        """If system or pipeline prompt fields are prompt-registry references,
        resolve them using the agent's own prompt registry.
        Returns a copy — no mutation."""
        registry = agent.prompt_registry
        changed = False

        # resolve agent-level system prompt
        system = agent.system
        if system and system.startswith("prompts."):
            system = registry.resolve(system)
            changed = True

        # resolve pipeline prompt references
        resolved_pipeline = []
        for step in agent.pipeline:
            new_step = step
            if step.type == "model" and step.prompt and step.prompt.startswith("prompts."):
                new_step = copy.copy(step)
                new_step.prompt = registry.resolve(step.prompt)
                changed = True
            if step.system and step.system.startswith("prompts."):
                if new_step is step:
                    new_step = copy.copy(step)
                new_step.system = registry.resolve(step.system)
                changed = True
            resolved_pipeline.append(new_step)

        if not changed:
            return agent  # nothing changed

        return AgentDefinition(
            agent_id=agent.agent_id,
            version=agent.version,
            model=agent.model,
            description=agent.description,
            system=system,
            pipeline=resolved_pipeline,
            tools=agent.tools,
            strategy=agent.strategy,
            temperature=agent.temperature,
            max_tokens=agent.max_tokens,
            params=agent.params,
            prompt_registry=agent.prompt_registry,
            definition_path=agent.definition_path,
        )
