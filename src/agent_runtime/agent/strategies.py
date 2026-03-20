"""Agent reasoning strategies — single-call, ReAct, custom.

Each strategy implements the agent loop by running the agent's internal
pipeline (an ordered sequence of model + tool steps):

- **single**: Run the pipeline once linearly.  Output = last step's output.
- **react**: Each react iteration runs the full pipeline.  The last model
  step's output decides whether to loop (no ``final_answer``) or stop.
  State is accumulated across iterations.
  # TODO: make accumulation configurable (option: clean slate per iteration)
- **custom**: Developer-provided strategy class.

Tool descriptions are NOT auto-injected into prompts.  Developers
control prompts entirely via the agent’s system/prompt fields and
the prompt registry.  The runtime only parses tool_call / final_answer
blocks from LLM output and executes tools from the agent's allowed list.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

from ..llm.client import LLMClient
from ..llm.types import LLMResponse
from ..tools.base import RuntimeContext, ToolResult
from ..tools.registry import ToolRegistry
from .definition import AgentDefinition, PipelineStep, StrategyConfig


# -- result types ----------------------------------------------------------


@dataclass
class ToolCall:
    """Record of a single tool invocation within an agent turn."""

    tool_name: str
    tool_input: Dict[str, Any]
    result: Optional[ToolResult] = None
    duration_ms: int = 0


@dataclass
class AgentTurn:
    """One iteration of the agent loop."""

    iteration: int
    llm_request: Dict[str, Any]
    llm_response: Optional[LLMResponse] = None
    tool_calls: List[ToolCall] = field(default_factory=list)
    observation: str = ""


@dataclass
class AgentResult:
    """Final output of an agent execution."""

    outputs: Dict[str, Any]
    trace: List[AgentTurn] = field(default_factory=list)
    iterations: int = 0
    token_usage: Dict[str, Any] = field(default_factory=dict)
    final_text: str = ""


# -- context ---------------------------------------------------------------


@dataclass
class AgentContext:
    """Execution context for an agent step."""

    run_id: str
    step_id: str
    state: Dict[str, Any]
    logger: Any = None


# -- strategy protocol -----------------------------------------------------


class AgentStrategyProtocol(Protocol):
    """Interface that all reasoning strategies implement."""

    async def run(
        self,
        agent: AgentDefinition,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        inputs: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult: ...


# -- tool-calling helpers --------------------------------------------------
# Tool descriptions are NOT auto-injected.  The developer controls the
# prompt (including tool instructions) via system/prompt_template.
# The runtime only parses tool_call / final_answer blocks and executes
# tools that are in the agent's allowed tools list.


def _parse_tool_calls(text: str) -> List[Dict[str, Any]]:
    """Extract ``tool_call`` JSON blocks from LLM response text."""
    calls: List[Dict[str, Any]] = []
    marker = "```tool_call"
    parts = text.split(marker)
    for part in parts[1:]:
        end = part.find("```")
        if end == -1:
            continue
        block = part[:end].strip()
        try:
            parsed = json.loads(block)
            if "tool" in parsed:
                calls.append(parsed)
        except json.JSONDecodeError:
            continue
    return calls


def _parse_final_answer(text: str) -> Optional[Dict[str, Any]]:
    """Extract ``final_answer`` JSON block from LLM response text."""
    marker = "```final_answer"
    if marker not in text:
        return None
    parts = text.split(marker)
    for part in parts[1:]:
        end = part.find("```")
        if end == -1:
            continue
        block = part[:end].strip()
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            continue
    return None


async def _execute_tool(
    tool_registry: ToolRegistry,
    name: str,
    tool_input: Dict[str, Any],
    context: AgentContext,
) -> ToolCall:
    """Execute a single tool and return a ToolCall record."""
    record = ToolCall(tool_name=name, tool_input=tool_input)
    try:
        tool = tool_registry.get(name)
        rt_ctx = RuntimeContext(
            run_id=context.run_id,
            step_id=context.step_id,
            state=context.state,
            logger=context.logger,
        )
        start = time.perf_counter()
        result = await tool.execute(tool_input, rt_ctx)
        record.duration_ms = int((time.perf_counter() - start) * 1000)
        record.result = result
    except Exception as exc:
        record.result = ToolResult(success=False, output=None, error=str(exc), metadata=None)
    return record


def _format_observation(record: ToolCall) -> str:
    """Format a tool call result as an observation string."""
    if record.result and record.result.success:
        obs = record.result.output
    else:
        error = record.result.error if record.result else "unknown"
        obs = f"Error: {error}"
    return f"Tool {record.tool_name} result: {json.dumps(obs, default=str)}"


def _aggregate_usage(turns: List[AgentTurn]) -> Dict[str, Any]:
    """Sum token usage across all LLM calls."""
    total: Dict[str, int] = {}
    for turn in turns:
        if turn.llm_response and turn.llm_response.usage:
            for k, v in turn.llm_response.usage.items():
                if isinstance(v, (int, float)):
                    total[k] = total.get(k, 0) + int(v)
    return total


# -- pipeline execution helpers --------------------------------------------


def _resolve_pipeline_model(agent: AgentDefinition, step: PipelineStep) -> str:
    """Return the model to use for a pipeline model step (step override or agent default)."""
    return step.model or agent.model


def _resolve_pipeline_system(agent: AgentDefinition, step: PipelineStep) -> Optional[str]:
    """Return the system prompt for a pipeline model step (step override or agent default)."""
    if step.system is not None:
        return step.system or None
    return agent.system or None


def _render_pipeline_prompt(template: str, state: Dict[str, Any]) -> str:
    """Render ``{{ path }}`` placeholders in a pipeline prompt.

    Uses dot-path resolution: ``{{ inputs.code }}`` or ``{{ analyze.issues }}``.
    """
    from ..utils import render_path_template
    return render_path_template(template, state)


def _resolve_pipeline_tool_inputs(
    raw_inputs: Optional[Dict[str, Any]], state: Dict[str, Any]
) -> Dict[str, Any]:
    """Resolve bare dot-path values in pipeline tool step inputs.

    Values that look like dot-paths (e.g. ``analyze.suggested_file``) are
    resolved from the pipeline state.  Other values pass through as literals.
    """
    if not raw_inputs:
        return {}
    resolved: Dict[str, Any] = {}
    for key, value in raw_inputs.items():
        if isinstance(value, str) and "." in value:
            parts = value.split(".")
            current: Any = state
            try:
                for part in parts:
                    if isinstance(current, dict) and part in current:
                        current = current[part]
                    else:
                        # not a valid path — treat as literal
                        resolved[key] = value
                        break
                else:
                    resolved[key] = current
            except (KeyError, TypeError):
                resolved[key] = value
        else:
            resolved[key] = value
    return resolved


async def _run_pipeline(
    agent: AgentDefinition,
    llm_client: LLMClient,
    tool_registry: ToolRegistry,
    inputs: Dict[str, Any],
    context: AgentContext,
    pipeline_state: Dict[str, Any],
    iteration: int,
) -> tuple[List[AgentTurn], Dict[str, Any], str]:
    """Execute the agent's pipeline once and return (turns, updated_state, last_model_text).

    ``pipeline_state`` is mutated: each step's output is written under
    its step id (e.g. ``{"analyze": {...}, "fetch": {...}}``).  The
    ``inputs`` key holds the original agent inputs.
    """
    turns: List[AgentTurn] = []
    last_model_text = ""
    params = {
        "temperature": agent.temperature,
        "max_tokens": agent.max_tokens,
        **agent.params,
    }

    for step in agent.pipeline:
        if step.type == "model":
            model_name = _resolve_pipeline_model(agent, step)
            system = _resolve_pipeline_system(agent, step)
            prompt = _render_pipeline_prompt(step.prompt, pipeline_state)

            response = llm_client.call(
                model=model_name, prompt=prompt, system=system, params=params,
            )
            turn = AgentTurn(
                iteration=iteration,
                llm_request={"prompt": prompt, "system": system, "step_id": step.id},
                llm_response=response,
            )

            # parse tool_call blocks inside model response (if any)
            inline_tool_calls = _parse_tool_calls(response.text)
            if inline_tool_calls:
                observations = []
                for tc in inline_tool_calls:
                    record = await _execute_tool(
                        tool_registry, tc["tool"], tc.get("input", {}), context,
                    )
                    turn.tool_calls.append(record)
                    observations.append(_format_observation(record))
                turn.observation = "\n".join(observations)

            turns.append(turn)

            # store model output in pipeline state under step id
            final = _parse_final_answer(response.text)
            step_output = final if final else {agent.output_key: response.text}
            pipeline_state[step.id] = step_output
            last_model_text = response.text

        elif step.type == "tool":
            tool_input = _resolve_pipeline_tool_inputs(step.inputs, pipeline_state)
            record = await _execute_tool(
                tool_registry, step.tool, tool_input, context,
            )
            turn = AgentTurn(
                iteration=iteration,
                llm_request={"step_id": step.id, "tool": step.tool},
                tool_calls=[record],
            )
            # store tool output in pipeline state
            if record.result and record.result.success:
                pipeline_state[step.id] = record.result.output or {}
            else:
                error_msg = record.result.error if record.result else "unknown"
                raise RuntimeError(
                    f"Pipeline tool step '{step.id}' failed: {error_msg}"
                )
            turns.append(turn)

    return turns, pipeline_state, last_model_text


# ── Strategy implementations ────────────────────────────────────────────


class SingleCallStrategy:
    """Run the agent's pipeline once, linearly.  Output = last step's output."""

    async def run(
        self,
        agent: AgentDefinition,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        inputs: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult:
        pipeline_state: Dict[str, Any] = {"inputs": inputs}
        turns, pipeline_state, last_text = await _run_pipeline(
            agent, llm_client, tool_registry, inputs, context,
            pipeline_state, iteration=1,
        )

        # output comes from the last pipeline step
        last_step_id = agent.pipeline[-1].id
        step_output = pipeline_state.get(last_step_id, {})
        final = _parse_final_answer(last_text) if last_text else None
        outputs = final if final else (step_output if isinstance(step_output, dict) else {agent.output_key: str(step_output)})

        return AgentResult(
            outputs=outputs,
            trace=turns,
            iterations=1,
            token_usage=_aggregate_usage(turns),
            final_text=last_text,
        )


class ReActStrategy:
    """ReAct loop: each iteration runs the full pipeline.

    The last model step in the pipeline decides whether to loop
    (no ``final_answer`` block) or stop (has ``final_answer`` block).
    State is accumulated across iterations.
    # TODO: make accumulation configurable (option: clean slate per iteration)
    """

    async def run(
        self,
        agent: AgentDefinition,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        inputs: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult:
        max_iter = agent.strategy.max_iterations
        # TODO: make referencing configurable (options: named ids, positional prev.*, accumulator)
        pipeline_state: Dict[str, Any] = {"inputs": inputs}
        all_turns: List[AgentTurn] = []

        for i in range(1, max_iter + 1):
            # expose iteration number in state for prompt templates
            pipeline_state["_iteration"] = i

            turns, pipeline_state, last_text = await _run_pipeline(
                agent, llm_client, tool_registry, inputs, context,
                pipeline_state, iteration=i,
            )
            all_turns.extend(turns)

            # check if the last model step produced a final_answer
            final = _parse_final_answer(last_text) if last_text else None
            if final:
                return AgentResult(
                    outputs=final,
                    trace=all_turns,
                    iterations=i,
                    token_usage=_aggregate_usage(all_turns),
                    final_text=last_text,
                )

            # evaluate stop_conditions against current pipeline state
            if agent.strategy.stop_conditions:
                from ..utils import safe_eval
                for cond in agent.strategy.stop_conditions:
                    try:
                        if safe_eval(cond, pipeline_state):
                            last_step_id = agent.pipeline[-1].id
                            step_output = pipeline_state.get(last_step_id, {})
                            outputs = step_output if isinstance(step_output, dict) else {agent.output_key: str(step_output)}
                            return AgentResult(
                                outputs=outputs,
                                trace=all_turns,
                                iterations=i,
                                token_usage=_aggregate_usage(all_turns),
                                final_text=last_text if last_text else "",
                            )
                    except Exception:
                        pass  # invalid condition — skip rather than crash the loop

            # no final_answer — plain text with no loop signal;
            # continue to next iteration (or stop at max)

        # max iterations reached — return last response as output
        last_step_id = agent.pipeline[-1].id
        step_output = pipeline_state.get(last_step_id, {})
        outputs = step_output if isinstance(step_output, dict) else {agent.output_key: str(step_output)}
        return AgentResult(
            outputs=outputs,
            trace=all_turns,
            iterations=max_iter,
            token_usage=_aggregate_usage(all_turns),
            final_text=last_text if last_text else "",
        )


# -- strategy resolver -----------------------------------------------------

BUILTIN_STRATEGIES: Dict[str, type] = {
    "single": SingleCallStrategy,
    "react": ReActStrategy,
}


def resolve_strategy(config: StrategyConfig) -> AgentStrategyProtocol:
    """Return a strategy instance for the given config."""
    if config.type == "custom":
        return _load_custom_strategy(config.custom_handler)
    cls = BUILTIN_STRATEGIES.get(config.type)
    if not cls:
        raise ValueError(f"Unknown strategy type: {config.type}")
    return cls()


def _load_custom_strategy(dotted_path: str) -> AgentStrategyProtocol:
    """Import a custom strategy class from a dotted module path."""
    if not dotted_path:
        raise ValueError("custom_handler path is required for custom strategy")
    module_path, _, class_name = dotted_path.rpartition(".")
    if not module_path or not class_name:
        raise ValueError(f"Invalid custom_handler path: {dotted_path}")
    import importlib

    module = importlib.import_module(module_path)
    cls = getattr(module, class_name, None)
    if cls is None:
        raise ValueError(f"Class '{class_name}' not found in '{module_path}'")
    return cls()
