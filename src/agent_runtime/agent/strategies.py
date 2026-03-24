"""Agent reasoning strategies — single-call, ReAct, custom.

Each strategy implements the agent loop by running the agent's internal
pipeline (an ordered sequence of model + tool steps):

- **single**: Run the pipeline once linearly.  Output = last step's output.
- **react**: Each react iteration runs the full pipeline.  The last model
  step's output decides whether to loop (no ``final_answer``) or stop.
  State is accumulated across iterations.
  # TODO(eng): make accumulation configurable (option: clean slate per iteration)
- **custom**: Developer-provided strategy class.

For ``react`` agents with declared tools, the runtime auto-injects
tool-calling instructions and available tool descriptions into the
system prompt (unless ``auto_tool_prompt: false`` is set on the agent).
The runtime parses ``tool_call`` / ``final_answer`` blocks from LLM
output and executes tools from the agent's allowed list.
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
# For react agents with tools, the runtime auto-injects tool descriptions
# and calling-convention instructions into the system prompt.  Set
# ``auto_tool_prompt: false`` on the agent to disable this behaviour.


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


# [Pain Point Partial] #N3 Cost Accounting is Invisible: Token usage is captured
#   per-provider and aggregated across agent turns. However, it is NOT persisted
#   on StepExecution records, there are no cost calculations, and there is no
#   run-level token/cost summary in the CLI.
# TODO(pain-point): Cost Accounting - Persist aggregated token usage on each
#   StepExecution record. Add a pricing table per model and compute per-step and
#   per-run cost. Surface it in `ai inspect` so developers know which step is
#   the expensive one before the invoice arrives.
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


def _build_tool_preamble(agent: AgentDefinition, tool_registry: ToolRegistry) -> str:
    """Generate text tool-calling instructions (used as system prompt preamble).

    Only injected when native function calling is NOT active, i.e. as fallback
    for models that don't support the provider's native tool-calling API.
    """
    lines = [
        "## Tool Calling",
        "You have access to the tools listed below. To call a tool, output a "
        "fenced code block tagged `tool_call` with a JSON object containing "
        '"tool" and "input" keys:',
        "",
        "```tool_call",
        '{"tool": "tool_name", "input": {"param": "value"}}',
        "```",
        "",
        "You may call multiple tools in a single response. You will receive "
        "each tool's result as an observation before your next response.",
        "",
        "## Returning Your Final Answer",
        "When you have completed the task, return a fenced code block tagged "
        "`final_answer` with a JSON object:",
        "",
        "```final_answer",
        '{"key": "value"}',
        "```",
        "",
        "## Available Tools",
        "",
    ]
    for tool_name in agent.tools:
        try:
            tool = tool_registry.get(tool_name)
            lines.append(f"### {tool.name}")
            lines.append(tool.description)
            schema = tool.input_schema
            if isinstance(schema, dict) and schema.get("properties"):
                params = []
                required = set(schema.get("required", []))
                for pname, pinfo in schema["properties"].items():
                    ptype = pinfo.get("type", "any")
                    req = ", required" if pname in required else ""
                    desc = pinfo.get("description", "")
                    suffix = f" — {desc}" if desc else ""
                    params.append(f"  - {pname} ({ptype}{req}){suffix}")
                lines.append("Parameters:")
                lines.extend(params)
            lines.append("")
        except Exception:
            lines.append(f"### {tool_name}")
            lines.append("(tool not found in registry)")
            lines.append("")
    return "\n".join(lines)


def _build_tool_schemas(
    agent: AgentDefinition, tool_registry: ToolRegistry
) -> List[Dict[str, Any]]:
    """Build a provider-agnostic tool schema list for native function calling.

    Returns a list of dicts with ``name``, ``description``, and ``parameters``
    (a JSON Schema object).  This list is passed to ``LLMClient.call(tools=...)``
    and forwarded to the adapter, which translates it into the provider's wire
    format (OpenAI ``tools``, Anthropic ``tools`` with ``input_schema``,
    Gemini ``function_declarations``).

    Tools that cannot be resolved from the registry are skipped silently —
    the same behaviour as ``_build_tool_preamble``.
    """
    schemas: List[Dict[str, Any]] = []
    for tool_name in agent.tools:
        try:
            tool = tool_registry.get(tool_name)
            schemas.append({
                "name": tool.name,
                "description": tool.description,
                # ``input_schema`` is already a JSON Schema dict.  Fall back to
                # an empty object schema if the tool didn't declare one.
                "parameters": tool.input_schema or {"type": "object", "properties": {}},
            })
        except Exception:  # noqa: BLE001
            pass
    return schemas


def _resolve_pipeline_system(
    agent: AgentDefinition,
    step: PipelineStep,
    tool_registry: Optional[ToolRegistry] = None,
    native_tools_active: bool = False,
) -> Optional[str]:
    """Return the system prompt for a pipeline model step.

    For ``react`` agents with declared tools and ``auto_tool_prompt`` enabled,
    text tool-calling instructions are prepended automatically — **unless**
    native function calling is active (``native_tools_active=True``), in which
    case the preamble is skipped to avoid confusing the model with conflicting
    calling conventions.
    """
    if step.system is not None:
        base = step.system or None
    else:
        base = agent.system or None

    if (
        tool_registry is not None
        and agent.tools
        and agent.auto_tool_prompt
        and agent.strategy.type == "react"
        and not native_tools_active
    ):
        preamble = _build_tool_preamble(agent, tool_registry)
        if base:
            return preamble + "\n\n" + base
        return preamble

    return base


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
    tools: Optional[List[Dict[str, Any]]] = None,
) -> tuple[List[AgentTurn], Dict[str, Any], str, bool]:

    """Execute the agent's pipeline once and return
    ``(turns, updated_state, last_model_text, last_had_native_calls)``.

    ``pipeline_state`` is mutated: each step's output is written under
    its step id (e.g. ``{"analyze": {...}, "fetch": {...}}``).  The
    ``inputs`` key holds the original agent inputs.

    ``last_had_native_calls`` is ``True`` when the final model step in this
    pipeline execution returned native tool calls.  ``ReActStrategy`` uses
    this to determine whether to continue looping: a model turn with no
    native calls (and no ``final_answer`` block) signals completion.
    """
    turns: List[AgentTurn] = []
    last_model_text = ""
    last_had_native_calls = False
    native_tools_active = bool(tools)
    params = {
        "temperature": agent.temperature,
        "max_tokens": agent.max_tokens,
        **agent.params,
    }

    for step in agent.pipeline:
        if step.type == "model":
            model_name = _resolve_pipeline_model(agent, step)
            system = _resolve_pipeline_system(
                agent, step, tool_registry,
                native_tools_active=native_tools_active,
            )
            prompt = _render_pipeline_prompt(step.prompt, pipeline_state)
            history = pipeline_state.get("_history")

            response = llm_client.call(
                model=model_name,
                prompt=prompt,
                system=system,
                params=params,
                history=history,
                context={"run_id": context.run_id, "step_id": context.step_id},
                tools=tools,
            )
            turn = AgentTurn(
                iteration=iteration,
                llm_request={"prompt": prompt, "system": system, "step_id": step.id},
                llm_response=response,
            )

            # ---------------------------------------------------------------------------
            # Tool dispatch: native path first, text-parsing fallback second.
            #
            # Native path  — ``response.tool_calls`` is populated by adapters when the
            #   provider's function-calling API is in use.  These are structured
            #   ``ToolCallRequest`` objects; no fragile text parsing required.
            #
            # Text fallback — ``_parse_tool_calls`` extracts ```tool_call``` code blocks
            #   from free-form LLM output.  Used for models that do not support native
            #   function calling or when ``tools`` was not passed to this pipeline.
            # ---------------------------------------------------------------------------
            observations: List[str] = []
            if response.tool_calls:
                # Native function-calling path.
                last_had_native_calls = True
                for tc in response.tool_calls:
                    record = await _execute_tool(
                        tool_registry, tc.tool_name, tc.tool_input, context,
                    )
                    turn.tool_calls.append(record)
                    observations.append(_format_observation(record))
            else:
                # Text-based fallback path.
                last_had_native_calls = False
                inline_tool_calls = _parse_tool_calls(response.text)
                for tc in inline_tool_calls:
                    record = await _execute_tool(
                        tool_registry, tc["tool"], tc.get("input", {}), context,
                    )
                    turn.tool_calls.append(record)
                    observations.append(_format_observation(record))

            if observations:
                turn.observation = "\n".join(observations)

            turns.append(turn)

            # Store model output in pipeline state under step id.
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
            # Store tool output in pipeline state.
            if record.result and record.result.success:
                pipeline_state[step.id] = record.result.output or {}
            else:
                error_msg = record.result.error if record.result else "unknown"
                raise RuntimeError(
                    f"Pipeline tool step '{step.id}' failed: {error_msg}"
                )
            turns.append(turn)

    return turns, pipeline_state, last_model_text, last_had_native_calls


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
        tools = _build_tool_schemas(agent, tool_registry) if agent.tools else None
        turns, pipeline_state, last_text, _ = await _run_pipeline(
            agent, llm_client, tool_registry, inputs, context,
            pipeline_state, iteration=1, tools=tools,
        )

        # Output comes from the last pipeline step.
        last_step_id = agent.pipeline[-1].id
        step_output = pipeline_state.get(last_step_id, {})
        final = _parse_final_answer(last_text) if last_text else None
        outputs = final if final else (
            step_output if isinstance(step_output, dict)
            else {agent.output_key: str(step_output)}
        )

        return AgentResult(
            outputs=outputs,
            trace=turns,
            iterations=1,
            token_usage=_aggregate_usage(turns),
            final_text=last_text,
        )


class ReActStrategy:
    """ReAct loop: each iteration runs the full pipeline.

    The last model step in the pipeline decides whether to loop or stop:
      - **Native function calling**: a turn with no ``tool_calls`` in the
        response signals completion (the model has nothing more to do).
      - **Text-based fallback**: a ``final_answer`` code block signals
        completion; absence of one continues the loop.
    State is accumulated across iterations.
    # TODO(eng): make accumulation configurable (option: clean slate per iteration)
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
        # TODO(eng): make referencing configurable (options: named ids, positional prev.*, accumulator)
        pipeline_state: Dict[str, Any] = {"inputs": inputs}
        all_turns: List[AgentTurn] = []
        tools = _build_tool_schemas(agent, tool_registry) if agent.tools else None

        for i in range(1, max_iter + 1):
            # Expose iteration number in state for prompt templates.
            pipeline_state["_iteration"] = i

            # ---------------------------------------------------------------------------
            # Build message history from previous turns.
            #
            # Turns that used native function calling emit structured history entries
            # (``_native_tool_calls`` / ``tool_results`` sentinel roles) so that each
            # adapter can translate them into its own wire format.
            #
            # Turns that used text-based tool calling emit plain assistant + user
            # observation entries — identical to the pre-native behaviour.
            # ---------------------------------------------------------------------------
            history: List[Dict[str, Any]] = []
            for turn in all_turns:
                if not turn.llm_response:
                    continue
                if turn.llm_response.tool_calls:
                    # Native path: replay the assistant's tool_call requests …
                    history.append({
                        "role": "assistant",
                        "content": turn.llm_response.text or "",
                        "_native_tool_calls": [
                            {"id": tc.id, "name": tc.tool_name, "input": tc.tool_input}
                            for tc in turn.llm_response.tool_calls
                        ],
                    })
                    # … then the tool execution results.
                    # ``turn.tool_calls`` is parallel to ``turn.llm_response.tool_calls``.
                    if turn.tool_calls:
                        history.append({
                            "role": "tool_results",
                            "_native_results": [
                                {
                                    "id": req.id,
                                    "name": req.tool_name,
                                    "content": json.dumps(
                                        executed.result.output
                                        if (executed.result and executed.result.success)
                                        else f"Error: {executed.result.error if executed.result else 'unknown'}",
                                        default=str,
                                    ),
                                }
                                for req, executed in zip(
                                    turn.llm_response.tool_calls, turn.tool_calls
                                )
                            ],
                        })
                else:
                    # Text-based path: plain assistant text + observation.
                    if turn.llm_response.text:
                        history.append({"role": "assistant", "content": turn.llm_response.text})
                    if turn.observation:
                        history.append({"role": "user", "content": f"Tool observation:\n{turn.observation}"})
            if history:
                pipeline_state["_history"] = history

            turns, pipeline_state, last_text, last_had_native_calls = await _run_pipeline(
                agent, llm_client, tool_registry, inputs, context,
                pipeline_state, iteration=i, tools=tools,
            )
            all_turns.extend(turns)

            # -- Stop condition 1: native path, model requested no more tools ------------
            # When native function calling is active, the model signals completion by
            # returning a turn with no tool_calls.  We distinguish this from the
            # text-based fallback by checking whether any turn in this iteration
            # actually executed a tool (native OR text): if not, the model is done.
            this_iteration_called_tools = any(t.tool_calls for t in turns)
            if tools and last_had_native_calls is False and not this_iteration_called_tools:
                last_step_id = agent.pipeline[-1].id
                step_output = pipeline_state.get(last_step_id, {})
                # Prefer an explicit final_answer block; fall back to step output.
                final = _parse_final_answer(last_text) if last_text else None
                outputs = final if final else (
                    step_output if isinstance(step_output, dict)
                    else {agent.output_key: str(step_output)}
                )
                return AgentResult(
                    outputs=outputs,
                    trace=all_turns,
                    iterations=i,
                    token_usage=_aggregate_usage(all_turns),
                    final_text=last_text,
                )

            # -- Stop condition 2: explicit final_answer block (text-based path) ---------
            final = _parse_final_answer(last_text) if last_text else None
            if final:
                return AgentResult(
                    outputs=final,
                    trace=all_turns,
                    iterations=i,
                    token_usage=_aggregate_usage(all_turns),
                    final_text=last_text,
                )

            # -- Stop condition 3: declarative stop_conditions ---------------------------
            if agent.strategy.stop_conditions:
                from ..utils import safe_eval
                for cond in agent.strategy.stop_conditions:
                    try:
                        if safe_eval(cond, pipeline_state):
                            last_step_id = agent.pipeline[-1].id
                            step_output = pipeline_state.get(last_step_id, {})
                            outputs = (
                                step_output if isinstance(step_output, dict)
                                else {agent.output_key: str(step_output)}
                            )
                            return AgentResult(
                                outputs=outputs,
                                trace=all_turns,
                                iterations=i,
                                token_usage=_aggregate_usage(all_turns),
                                final_text=last_text if last_text else "",
                            )
                    except Exception:  # noqa: BLE001
                        pass  # invalid condition — skip rather than crash the loop

            # No stop signal — continue to next iteration (or stop at max).

        # Max iterations reached — return last response as output.
        last_step_id = agent.pipeline[-1].id
        step_output = pipeline_state.get(last_step_id, {})
        outputs = (
            step_output if isinstance(step_output, dict)
            else {agent.output_key: str(step_output)}
        )
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
