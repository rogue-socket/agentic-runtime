from __future__ import annotations

"""File: src/agent_runtime/core.py

Purpose:
Implement runtime execution engine, run/step datamodels, and control flow.

Description:
Defines the `Executor` that runs workflow steps with retry and agent/function/tool
dispatch, branch routing, state persistence, and terminal status updates.

Key Components:
- Dataclasses: `Run`, `RunState`, `StepDefinition`, `StepExecution`
- Execution orchestrator: `Executor`
- Retry/backoff and branch resolution helpers

Dependencies:
- Storage abstraction, memory manager, tool registry, runtime state utilities

Inputs/Outputs:
- Input: normalized workflow steps and initial run state
- Output: persisted run/step/state records and terminal run result

Side Effects:
- Writes to storage, may sleep for backoff, executes tool handlers.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set
import copy
import uuid
import time
import asyncio
import traceback

from .errors import BranchResolutionError, StepExecutionError, WorkflowIntegrityError
from .logging import StructuredLogger
from .memory.base import MemoryManager
from .models import (
    NextRule,
    RetryPolicy,
    Run,
    RunState,
    StepDefinition,
    StepExecution,
    StepStatus,
)
from .observability import serialize_agent_trace
from .state import RuntimeState
from .storage.base import Storage
from .tools.base import RuntimeContext, ToolResult
from .tools.registry import ToolRegistry
from .tools.validation import validate_input
from .utils import StateDict, build_step_input, format_template, safe_eval, utc_now

import re as _re

from .agent.executor import AgentExecutor
from .agent.strategies import AgentContext

# Lifecycle event callback signature.
# Receives an event name (e.g. "STEP_START") and a payload dict.
EventCallback = Callable[[str, Dict[str, Any]], None]


def _format_step_error(exc: Exception, *, include_trace: bool = False) -> str:
    """Format step errors with optional traceback context for debugging."""
    base = f"{type(exc).__name__}: {exc}"
    if not include_trace:
        return base

    trace_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()
    if not trace_text:
        return base

    lines = trace_text.splitlines()
    if len(lines) > 40:
        trace_text = "\n".join(lines[-40:])
    return f"{base}\n{trace_text}"


# [Pain Point Solved] #10 Rebuild Same Infra Every Project: The Executor handles
#   orchestration, persistence, retries, branching, state management, and event
#   callbacks — the 80% of infra work that's the same for every agent project.
class Executor:
    """Execute workflow steps and persist deterministic run history."""

    def __init__(
        self,
        steps: List[StepDefinition],
        storage: Storage,
        logger: Optional[StructuredLogger],
        memory_manager: MemoryManager,
        tool_registry: ToolRegistry,
        overwrite_policy: str = "warn",
        on_event: Optional[EventCallback] = None,
        agent_registry: Any = None,
        llm_client: Any = None,
        default_model: str = "",
        heartbeat_interval_s: float = 5.0,
        latency_budget_ms: Optional[int] = None,
    ) -> None:
        """Initialize executor dependencies and step lookup tables."""
        self.steps = steps
        self.step_order = [step.step_id for step in steps]
        self.step_map = {step.step_id: step for step in steps}
        self.storage = storage
        self.logger = logger
        self.memory_manager = memory_manager
        self.tool_registry = tool_registry
        self.overwrite_policy = overwrite_policy
        self.on_event = on_event
        self.agent_registry = agent_registry
        self.llm_client = llm_client
        self.default_model = default_model
        self.heartbeat_interval_s = max(0.05, float(heartbeat_interval_s))
        self.latency_budget_ms = latency_budget_ms

    def _emit(self, event: str, payload: Dict[str, Any]) -> None:
        """Fire the on_event callback if registered."""
        if self.on_event is None:
            return
        try:
            self.on_event(event, payload)
        except Exception as exc:  # noqa: BLE001
            if self.logger:
                self.logger.error(
                    "EVENT_CALLBACK_ERROR",
                    {
                        "event": event,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )


    # -- Step dispatch helpers ------------------------------------------------
    # Each dispatch method returns (output_dict, handler_duration_ms, tool_duration_ms).
    # Agent/function return (output, handler_ms, None); tool returns (output, None, tool_ms).
    # The two duration slots are mutually exclusive.
    # May mutate `execution` to set metadata (token_usage, model_name, trace).

    async def _run_with_timeout_and_heartbeat(
        self,
        coro: Any,
        *,
        step_def: StepDefinition,
        run_id: str,
        execution_index: int,
        attempt: int,
    ) -> tuple[Any, int]:
        """Wrap an async coroutine with heartbeat emission and optional timeout.

        Returns (result, elapsed_ms).
        """
        call_start = time.monotonic()
        self._emit_step_progress(
            run_id=run_id,
            step_id=step_def.step_id,
            step_type=step_def.step_type,
            execution_index=execution_index,
            attempt=attempt,
            phase="dispatch",
            elapsed_ms=0,
        )

        wrapped = self._await_with_heartbeat(
            coro,
            run_id=run_id,
            step_id=step_def.step_id,
            step_type=step_def.step_type,
            execution_index=execution_index,
            attempt=attempt,
        )

        if step_def.timeout_ms:
            t_sec = float(step_def.timeout_ms) / 1000.0
            try:
                result = await asyncio.wait_for(wrapped, timeout=t_sec)
            except asyncio.TimeoutError:
                elapsed = int((time.monotonic() - call_start) * 1000)
                self._emit_step_progress(
                    run_id=run_id,
                    step_id=step_def.step_id,
                    step_type=step_def.step_type,
                    execution_index=execution_index,
                    attempt=attempt,
                    phase="timeout",
                    elapsed_ms=elapsed,
                    error=f"{step_def.step_type.title()} step timed out after {step_def.timeout_ms}ms",
                )
                raise StepExecutionError(
                    f"{step_def.step_type.title()} step timed out after {step_def.timeout_ms}ms"
                )
        else:
            result = await wrapped

        elapsed = int((time.monotonic() - call_start) * 1000)
        self._emit_step_progress(
            run_id=run_id,
            step_id=step_def.step_id,
            step_type=step_def.step_type,
            execution_index=execution_index,
            attempt=attempt,
            phase="complete",
            elapsed_ms=elapsed,
        )
        return result, elapsed

    async def _dispatch_agent(
        self,
        step_def: StepDefinition,
        step_input: Any,
        snapshot: StateDict,
        run: Run,
        execution_index: int,
        attempt: int,
        execution: StepExecution,
    ) -> tuple[Dict[str, Any], Optional[int], None]:
        """Dispatch an agent step — returns (output, handler_duration_ms, None)."""
        if not step_def.agent_id:
            raise StepExecutionError("Agent step missing agent_id.")
        if not self.agent_registry:
            raise StepExecutionError("AgentRegistry not configured.")
        if not self.llm_client:
            raise StepExecutionError("LLMClient not configured.")

        agent_def = self.agent_registry.get(step_def.agent_id, step_def.agent_version)
        if not agent_def.model and self.default_model:
            agent_def = copy.copy(agent_def)
            agent_def.model = self.default_model

        agent_executor = AgentExecutor(self.llm_client, self.tool_registry, self.logger)
        agent_ctx = AgentContext(
            run_id=run.run_id,
            step_id=step_def.step_id,
            state=snapshot,
            logger=self.logger,
            on_event=self._emit,
            execution_index=execution_index,
            attempt=attempt,
        )
        agent_input = step_input if step_def.input_spec is not None else snapshot

        agent_result, handler_duration_ms = await self._run_with_timeout_and_heartbeat(
            agent_executor.execute(agent_def, agent_input, agent_ctx),
            step_def=step_def,
            run_id=run.run_id,
            execution_index=execution_index,
            attempt=attempt,
        )

        execution.token_usage = agent_result.token_usage
        execution.cost_usd = agent_result.cost_usd
        if agent_result.trace:
            for _turn in reversed(agent_result.trace):
                if _turn.llm_response and _turn.llm_response.model:
                    execution.model_name = _turn.llm_response.model
                    break
        # TODO(pain-point): Hallucination Guardrails -
        #   The agent output is stored as-is. For extraction tasks,
        #   add an optional `grounding_validator` hook that cross-
        #   checks agent output against source input — catching
        #   invented data before it flows into your database.
        execution.agent_trace = serialize_agent_trace(agent_result.trace)
        return agent_result.outputs, handler_duration_ms, None

    def _dispatch_function(
        self,
        step_def: StepDefinition,
        step_input: Any,
        snapshot: StateDict,
    ) -> tuple[Dict[str, Any], Optional[int], None]:
        """Dispatch a function step — returns (output, handler_duration_ms, None).

        Note: timeout_ms is not enforced for function steps since they run
        synchronously in-process. Consider wrapping in asyncio.wait_for if
        timeout support is needed.
        """
        if step_def.function_callable is None:
            raise StepExecutionError("Function step missing resolved callable.")
        # Merge snapshot + declared inputs so functions see a consistent shape
        # whether or not the step declares an `inputs:` block. Snapshot keys
        # (`inputs`, `steps`, `runtime`) are always present; declared inputs
        # land at the top level and win on collision. See issue #14.
        if step_def.input_spec is not None:
            snapshot_dict = snapshot.to_dict() if isinstance(snapshot, RuntimeState) else snapshot
            step_input_dict = step_input.to_dict() if isinstance(step_input, RuntimeState) else step_input
            func_input = {**snapshot_dict, **step_input_dict}
        else:
            func_input = snapshot.to_dict() if isinstance(snapshot, RuntimeState) else snapshot
        call_start = time.monotonic()
        output = step_def.function_callable(func_input)
        handler_duration_ms = int((time.monotonic() - call_start) * 1000)
        return output, handler_duration_ms, None

    async def _dispatch_tool(
        self,
        step_def: StepDefinition,
        step_input: Any,
        snapshot: StateDict,
        run: Run,
        execution_index: int,
        attempt: int,
    ) -> tuple[Dict[str, Any], None, Optional[int]]:
        """Dispatch a tool step — returns (output, None, tool_duration_ms)."""
        if not step_def.tool_name:
            raise StepExecutionError("Missing tool name.")
        tool = self.tool_registry.get(step_def.tool_name)
        tool_input = (
            step_input
            if step_def.input_spec is not None
            else format_template(step_def.raw_input or {}, snapshot)
        )

        (output, inner_tool_ms), elapsed_ms = await self._run_with_timeout_and_heartbeat(
            self._execute_tool_async(tool, tool_input, run.run_id, step_def.step_id, snapshot),
            step_def=step_def,
            run_id=run.run_id,
            execution_index=execution_index,
            attempt=attempt,
        )
        return output, None, inner_tool_ms if inner_tool_ms is not None else elapsed_ms

    # -- End dispatch helpers -------------------------------------------------

    def _mark_run_failed_best_effort(self, run: Run, error: str) -> Optional[Exception]:
        """Function implementation."""
        if run.status != StepStatus.FAILED:
            run.set_status(StepStatus.FAILED, error=error, completed_at=utc_now().isoformat())
        else:
            if run.completed_at is None:
                run.completed_at = utc_now().isoformat()
            if not run.error:
                run.error = error

        try:
            self.storage.update_run_status(
                run.run_id,
                run.status,
                run.error,
                completed_at=run.completed_at,
            )
            return None
        except Exception as storage_exc:  # noqa: BLE001
            if self.logger:
                self.logger.error(
                    "RUN_STATUS_PERSIST_ERROR",
                    {
                        "run_id": run.run_id,
                        "status": run.status,
                        "error": f"{type(storage_exc).__name__}: {storage_exc}",
                    },
                )
            return storage_exc
        finally:
            run.freeze()

    def _emit_step_progress(
        self,
        *,
        run_id: str,
        step_id: str,
        step_type: str,
        execution_index: int,
        attempt: int,
        phase: str,
        elapsed_ms: Optional[int] = None,
        error: Optional[str] = None,
    ) -> None:
        """Emit a normalized progress event for long-running step execution."""
        payload: Dict[str, Any] = {
            "run_id": run_id,
            "step_id": step_id,
            "step_type": step_type,
            "execution_index": execution_index,
            "attempt": attempt,
            "phase": phase,
        }
        if elapsed_ms is not None:
            payload["elapsed_ms"] = elapsed_ms
        if error is not None:
            payload["error"] = error
        self._emit("STEP_PROGRESS", payload)

    def run(
        self,
        workflow_id: str,
        initial_state: StateDict,
        workflow_inputs: Optional[Dict[str, Any]] = None,
        workflow_version: Optional[str] = None,
        on_error: str = "fail_fast",
        workflow_hash: Optional[str] = None,
        workflow_yaml: Optional[str] = None,
        workflow_steps: Optional[List[str]] = None,
        input_hash: Optional[str] = None,
    ) -> Run:
        """Create a new run and execute workflow from the first step.

        Safe to call from inside a running event loop — the workflow is
        dispatched to a worker thread with its own loop. For native async
        usage prefer :meth:`run_async`.
        """
        from ._async_compat import run_coro_blocking
        return run_coro_blocking(
            self.run_async(
                workflow_id=workflow_id,
                initial_state=initial_state,
                workflow_inputs=workflow_inputs,
                workflow_version=workflow_version,
                on_error=on_error,
                workflow_hash=workflow_hash,
                workflow_yaml=workflow_yaml,
                workflow_steps=workflow_steps,
                input_hash=input_hash,
            )
        )

    async def run_async(
        self,
        workflow_id: str,
        initial_state: StateDict,
        workflow_inputs: Optional[Dict[str, Any]] = None,
        workflow_version: Optional[str] = None,
        on_error: str = "fail_fast",
        workflow_hash: Optional[str] = None,
        workflow_yaml: Optional[str] = None,
        workflow_steps: Optional[List[str]] = None,
        input_hash: Optional[str] = None,
        on_event: Optional[EventCallback] = None,
    ) -> Run:
        """Async: create a new run and execute workflow from the first step."""
        if not self.step_order:
            raise StepExecutionError("Workflow must contain at least one step.")

        # Per-call on_event overrides the instance-level callback.
        prev_on_event = self.on_event
        if on_event is not None:
            self.on_event = on_event

        resolved_inputs = copy.deepcopy(initial_state)
        if workflow_inputs:
            for name, spec in workflow_inputs.items():
                if name in resolved_inputs:
                    continue
                if not isinstance(spec, dict):
                    continue
                if "default" in spec:
                    resolved_inputs[name] = copy.deepcopy(spec["default"])

        actual_run_id = str(uuid.uuid4())
        run = Run(
            run_id=actual_run_id,
            workflow_id=workflow_id,
            workflow_version=workflow_version,
            workflow_hash=workflow_hash,
            workflow_yaml=workflow_yaml,
            workflow_steps=workflow_steps,
            input_hash=input_hash,
            status=StepStatus.RUNNING,
            created_at=utc_now().isoformat(),
            started_at=utc_now().isoformat(),
            state=RunState(
                _data={
                    "inputs": copy.deepcopy(resolved_inputs),
                    "steps": {},
                    "runtime": {
                        "workflow_id": workflow_id,
                        "run_id": actual_run_id,
                    },
                },
                _overwrite_policy=self.overwrite_policy,
                _logger=self.logger,
            ),
        )

        state_version = 0

        # Persist run record and initial state version atomically.
        # A crash between these would leave a run with no state — unresumable.
        with self.storage.transaction():
            self.storage.create_run(run)
            self.storage.save_state(run.run_id, None, state_version, run.state.data)

        self._emit("RUN_START", {"run_id": run.run_id, "workflow_id": workflow_id})

        try:
            return await self._execute_steps_async(
                run,
                start_step_id=self.step_order[0],
                on_error=on_error,
                state_version=state_version,
            )
        finally:
            self.on_event = prev_on_event

    def resume(
        self,
        run: Run,
        resume_state: StateDict,
        start_step_id: str,
        on_error: str,
        state_version: int,
        workflow_hash: Optional[str] = None,
    ) -> Run:
        """Resume a previously failed run from the given step.

        Safe to call from inside a running event loop — the workflow is
        dispatched to a worker thread with its own loop. For native async
        usage prefer :meth:`resume_async`.
        """
        from ._async_compat import run_coro_blocking
        return run_coro_blocking(
            self.resume_async(
                run=run,
                resume_state=resume_state,
                start_step_id=start_step_id,
                on_error=on_error,
                state_version=state_version,
                workflow_hash=workflow_hash,
            )
        )

    async def resume_async(
        self,
        run: Run,
        resume_state: StateDict,
        start_step_id: str,
        on_error: str,
        state_version: int,
        workflow_hash: Optional[str] = None,
    ) -> Run:
        """Async: resume a failed run from a starting step id."""
        if not run.workflow_hash:
            raise WorkflowIntegrityError(
                "Cannot safely resume because the original run does not have a stored workflow hash. "
                "Re-run the workflow from the start under the current runtime."
            )
        if not workflow_hash:
            raise WorkflowIntegrityError(
                "Cannot safely resume without a workflow hash for the current workflow definition."
            )
        if run.workflow_hash != workflow_hash:
            raise WorkflowIntegrityError(
                f"Workflow has been modified since original run. "
                f"Original hash: {run.workflow_hash}, current hash: {workflow_hash}. "
                f"Cannot safely resume — the workflow YAML must match the original run."
            )
        run.unfreeze()
        run.state = RunState(
            _data=copy.deepcopy(resume_state),
            _overwrite_policy=self.overwrite_policy,
            _logger=self.logger,
        )
        run.set_status(StepStatus.RUNNING)
        if run.started_at is None:
            run.started_at = utc_now().isoformat()
        self.storage.update_run_status(run.run_id, run.status, None, started_at=run.started_at)
        return await self._execute_steps_async(
            run,
            start_step_id=start_step_id,
            on_error=on_error,
            state_version=state_version,
        )

    async def _execute_steps_async(self, run: Run, start_step_id: str, on_error: str, state_version: int) -> Run:
        """Execute steps sequentially/branched from a starting step id."""
        had_errors = False
        current_step_id: Optional[str] = start_step_id
        execution_index = self.storage.load_max_execution_index(run.run_id) + 1
        try:
            return await self.__execute_steps_loop(
                run, current_step_id, on_error, state_version, had_errors, execution_index
            )
        except Exception as exc:  # noqa: BLE001
            persist_error = self._mark_run_failed_best_effort(
                run,
                error=f"{type(exc).__name__}: {exc}",
            )
            if persist_error is not None and persist_error is not exc:
                if hasattr(exc, "add_note"):
                    exc.add_note(
                        "Additionally failed to persist FAILED run status: "
                        f"{type(persist_error).__name__}: {persist_error}"
                    )
            raise

    async def __execute_steps_loop(
        self, run: Run, current_step_id: Optional[str], on_error: str,
        state_version: int, had_errors: bool, execution_index: int,
    ) -> Run:
        """Function implementation."""
        visited: Set[str] = set()
        run_start_mono = time.monotonic()
        while current_step_id is not None:
            # --- Workflow-level latency budget check ---
            if self.latency_budget_ms is not None:
                elapsed_ms = int((time.monotonic() - run_start_mono) * 1000)
                if elapsed_ms > self.latency_budget_ms:
                    raise StepExecutionError(
                        f"Workflow latency budget exceeded: {elapsed_ms}ms > {self.latency_budget_ms}ms "
                        f"(before starting step '{current_step_id}')"
                    )
            if current_step_id not in self.step_map:
                raise StepExecutionError(f"Unknown step id: {current_step_id}")
            if current_step_id in visited:
                raise BranchResolutionError(
                    f"Circular branch detected: step '{current_step_id}' has already been executed in this run."
                )
            visited.add(current_step_id)
            step_def = self.step_map[current_step_id]
            if step_def.step_id in run.state.data.get("steps", {}):
                raise StepExecutionError(f"Duplicate step execution: {step_def.step_id}")
            execution = StepExecution(
                step_id=step_def.step_id,
                step_type=step_def.step_type,
                status=StepStatus.RUNNING,
                started_at=utc_now().isoformat(),
                execution_index=execution_index,
            )
            run.add_step(execution)

            self._emit("STEP_START", {
                "run_id": run.run_id,
                "step_id": step_def.step_id,
                "step_type": step_def.step_type,
                "execution_index": execution_index,
            })

            step_start_mono = time.monotonic()

            try:
                max_attempts = step_def.retry.attempts if step_def.retry else 1
                backoff = step_def.retry.backoff if step_def.retry else "fixed"
                initial_delay = step_def.retry.initial_delay if step_def.retry else 0.0

                output = None
                last_error: Optional[Exception] = None
                degraded_error: Optional[str] = None
                handler_duration_ms: Optional[int] = None
                tool_duration_ms: Optional[int] = None
                for attempt in range(1, max_attempts + 1):
                    snapshot = run.state.snapshot()
                    # Only capture state_before on the first attempt so replay/diff
                    # features see the original pre-step state, not a post-failure snapshot.
                    if attempt == 1:
                        execution.state_before = copy.deepcopy(snapshot)
                    self.memory_manager.hydrate_state(snapshot)
                    if step_def.input_spec is not None:
                        step_input = build_step_input(step_def.input_spec, snapshot)
                    else:
                        step_input = snapshot
                    if step_def.raw_input:
                        if not isinstance(step_input, dict):
                            raise StepExecutionError("Step input must be a dict.")
                        step_input = copy.deepcopy(step_input)
                        step_input["__llm__"] = copy.deepcopy(step_def.raw_input)
                        step_input["__llm_context__"] = {
                            "run_id": run.run_id,
                            "step_id": step_def.step_id,
                        }
                    step_input_state = RuntimeState(step_input, enforce_structure=False)
                    persisted_input = step_input_state.to_dict()
                    # Strip internal LLM context before persisting — these may
                    # contain raw prompts or interpolated secrets that should
                    # not be stored in the execution record.
                    persisted_input.pop("__llm__", None)
                    persisted_input.pop("__llm_context__", None)
                    execution.input = copy.deepcopy(persisted_input)
                    execution.attempt_count = attempt

                    try:
                        # [Pain Point Solved] #6 Mixing Step Types: Three separate
                        # dispatch paths — agent (LLM), function (deterministic),
                        # tool (external I/O) — so a formatting function doesn't
                        # need an LLM wrapper.
                        if step_def.step_type == "agent":
                            output, handler_duration_ms, _ = await self._dispatch_agent(
                                step_def, step_input, snapshot, run,
                                execution_index, attempt, execution,
                            )
                        elif step_def.step_type == "function":
                            output, handler_duration_ms, _ = self._dispatch_function(
                                step_def, step_input, snapshot,
                            )
                        elif step_def.step_type == "tool":
                            output, _, tool_duration_ms = await self._dispatch_tool(
                                step_def, step_input, snapshot, run,
                                execution_index, attempt,
                            )
                        else:
                            raise StepExecutionError(f"Unknown step type: {step_def.step_type}")

                        last_error = None
                        break
                    except Exception as exc:  # noqa: BLE001
                        last_error = exc
                        execution.last_error = _format_step_error(
                            exc,
                            include_trace=step_def.step_type in {"function", "tool"},
                        )
                        if step_def.step_type in {"agent", "tool"}:
                            self._emit_step_progress(
                                run_id=run.run_id,
                                step_id=step_def.step_id,
                                step_type=step_def.step_type,
                                execution_index=execution_index,
                                attempt=attempt,
                                phase="error",
                                error=execution.last_error,
                            )
                        if attempt < max_attempts:
                            delay = _compute_backoff_delay(attempt, backoff, initial_delay)
                            self._emit("STEP_RETRY", {
                                "run_id": run.run_id,
                                "step_id": step_def.step_id,
                                "step_type": step_def.step_type,
                                "execution_index": execution_index,
                                "attempt": attempt,
                                "next_attempt": attempt + 1,
                                "max_attempts": max_attempts,
                                "error": execution.last_error,
                                "backoff": backoff,
                                "delay_ms": int(delay * 1000),
                            })
                            if delay > 0:
                                await asyncio.sleep(delay)

                if last_error is not None:
                    if step_def.optional:
                        degraded_error = f"{type(last_error).__name__}: {last_error}"
                        execution.last_error = degraded_error
                        output = copy.deepcopy(step_def.default_output) if step_def.default_output is not None else {}
                        if not isinstance(output, dict):
                            raise StepExecutionError("Optional step default output must be a dict.")
                    else:
                        raise last_error

                if output is None or not isinstance(output, dict):
                    raise StepExecutionError("Step handler must return a dict.")
                if step_def.output_contract:
                    expected = set(step_def.output_contract)
                    actual = set(output.keys())
                    missing = expected - actual
                    extra = actual - expected
                    if missing:
                        raise StepExecutionError(
                            f"Output contract violation for step {step_def.step_id}: missing keys {sorted(missing)}"
                        )
                    if extra:
                        raise StepExecutionError(
                            f"Output contract violation for step {step_def.step_id}: undeclared keys {sorted(extra)}"
                        )
                if step_def.output_schema:
                    _validate_output_schema(step_def.step_id, output, step_def.output_schema)

                # Keep core state namespaces immutable from step output payloads.
                reserved_keys = {"inputs", "runtime", "steps"}
                reserved = sorted(key for key in output.keys() if key in reserved_keys)
                if reserved:
                    raise StepExecutionError(
                        f"Step output cannot include reserved key(s): {', '.join(reserved)}"
                    )

                # Inputs are immutable during execution; step handlers operate on snapshots.
                if run.state.data.get("inputs") != snapshot.get("inputs"):
                    raise StepExecutionError("Input state is immutable and cannot be modified by steps.")

                # Explicitly allow output overwrite only when policy is set to allow.
                if step_def.step_id in run.state.data.get("steps", {}) and self.overwrite_policy != "allow":
                    raise StepExecutionError(
                        f"Step output overwrite not allowed for '{step_def.step_id}' "
                        f"(set overwrite_policy=allow to permit)"
                    )
                # Extract side-effect declarations from tool output BEFORE
                # persisting to state — prevents __side_effects__ metadata
                # from leaking into the state tree.
                _side_effects = output.pop("__side_effects__", None)
                if isinstance(_side_effects, list):
                    execution.side_effects = _side_effects

                run.state.set_step_output(step_def.step_id, output)
                self.memory_manager.persist_state(run.state.data)
                execution.state_after = copy.deepcopy(run.state.data)

                execution.output = output
                execution.status = StepStatus.COMPLETED
                execution.handler_duration_ms = handler_duration_ms
                execution.tool_duration_ms = tool_duration_ms
                if degraded_error is not None:
                    self._emit("STEP_DEGRADED", {
                        "run_id": run.run_id,
                        "step_id": step_def.step_id,
                        "step_type": step_def.step_type,
                        "execution_index": execution_index,
                        "error": degraded_error,
                        "default_output_used": True,
                    })
            except Exception as exc:  # noqa: BLE001
                execution.status = StepStatus.FAILED
                include_trace = step_def.step_type in {"function", "tool"}
                execution.error = execution.last_error or _format_step_error(exc, include_trace=include_trace)
                if execution.last_error is None:
                    execution.last_error = execution.error
                had_errors = True
                if on_error == "fail_fast":
                    run.set_status(StepStatus.FAILED, error=execution.error, completed_at=utc_now().isoformat())
            finally:
                if execution.finished_at is None:
                    execution.finished_at = utc_now().isoformat()
                # Use monotonic clock for accurate duration — avoids ISO string
                # round-trip precision loss and timezone edge cases.
                execution.duration_ms = int((time.monotonic() - step_start_mono) * 1000)

            if execution.status == StepStatus.COMPLETED:
                self._emit("STEP_COMPLETE", {
                    "run_id": run.run_id,
                    "step_id": step_def.step_id,
                    "step_type": step_def.step_type,
                    "attempt_count": execution.attempt_count,
                    "last_error": execution.last_error,
                    "duration_ms": execution.duration_ms,
                    "handler_duration_ms": execution.handler_duration_ms,
                    "tool_duration_ms": execution.tool_duration_ms,
                })
            else:
                self._emit("STEP_ERROR", {
                    "run_id": run.run_id,
                    "step_id": step_def.step_id,
                    "step_type": step_def.step_type,
                    "error": execution.error,
                    "attempt_count": execution.attempt_count,
                    "last_error": execution.last_error,
                    "duration_ms": execution.duration_ms,
                    "handler_duration_ms": execution.handler_duration_ms,
                    "tool_duration_ms": execution.tool_duration_ms,
                })

            # Resolve next step before persisting so it's captured on the record.
            if execution.status != StepStatus.FAILED or on_error != "fail_fast":
                resolved_next = self._resolve_next_step(step_def, run.state.data)
                execution.next_step_resolved = resolved_next

            # Persist the step record, state snapshot, and (on failure) status
            # update together.  If any write fails or the process crashes
            # mid-batch, SQLite rolls back the entire group — no orphaned
            # step records without matching state versions.
            with self.storage.transaction():
                self.storage.append_step(run.run_id, execution)

                if execution.status == StepStatus.FAILED and on_error == "fail_fast":
                    self.storage.update_run_status(
                        run.run_id,
                        run.status,
                        run.error,
                        completed_at=run.completed_at,
                    )
                else:
                    state_version += 1
                    self.storage.save_state(run.run_id, execution.step_id, state_version, run.state.data)

            if execution.status == StepStatus.FAILED and on_error == "fail_fast":
                run.freeze()
                break

            execution_index += 1

            current_step_id = execution.next_step_resolved

        if run.status != StepStatus.FAILED:
            final_status = StepStatus.COMPLETED_WITH_ERRORS if had_errors else StepStatus.COMPLETED
            run.set_status(final_status, completed_at=utc_now().isoformat())
            self.storage.update_run_status(
                run.run_id,
                run.status,
                None,
                completed_at=run.completed_at,
            )
            run.freeze()

        # Final memory persist with run outcome so episodic memory can record
        # the completed episode (status, error) alongside step outputs.
        try:
            run.unfreeze()
            run.state.runtime().set("runtime.status", run.status)
            run.state.runtime().set("runtime.error", run.error or "")
            self.memory_manager.persist_state(run.state.snapshot())
        except Exception as mem_exc:  # noqa: BLE001
            # Best-effort: don't fail the run for memory persistence, but log
            # the error so it's diagnosable rather than silently swallowed.
            if self.logger:
                self.logger.error(
                    "MEMORY_PERSIST_ERROR",
                    {
                        "run_id": run.run_id,
                        "error": f"{type(mem_exc).__name__}: {mem_exc}",
                    },
                )
        finally:
            run.freeze()

        self._emit("RUN_COMPLETE", {
            "run_id": run.run_id,
            "status": run.status,
            "error": run.error,
        })

        # Release usage counters for this run to prevent unbounded memory growth
        # in long-lived LLMClient instances (e.g. webhook-triggered services).
        if self.llm_client is not None and hasattr(self.llm_client, "clear_run_usage"):
            self.llm_client.clear_run_usage(run.run_id)

        return run

    async def _await_with_heartbeat(
        self,
        coro: Any,
        *,
        run_id: str,
        step_id: str,
        step_type: str,
        execution_index: int,
        attempt: int,
    ) -> Any:
        """Await a coroutine while periodically emitting step heartbeat events."""
        task = asyncio.create_task(coro)
        started = time.monotonic()
        try:
            while True:
                done, _ = await asyncio.wait({task}, timeout=self.heartbeat_interval_s)
                if task in done:
                    return await task
                self._emit("STEP_HEARTBEAT", {
                    "run_id": run_id,
                    "step_id": step_id,
                    "step_type": step_type,
                    "execution_index": execution_index,
                    "attempt": attempt,
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                })
                self._emit_step_progress(
                    run_id=run_id,
                    step_id=step_id,
                    step_type=step_type,
                    execution_index=execution_index,
                    attempt=attempt,
                    phase="heartbeat",
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                )
        except asyncio.CancelledError:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            raise

    async def _execute_tool_async(
        self,
        tool,
        tool_input: Dict[str, Any],
        run_id: str,
        step_id: str,
        state: StateDict,
    ) -> tuple[Dict[str, Any], int]:
        """Execute tool with validation, retries, and structured events."""
        validate_input(tool_input, tool.input_schema)
        context = RuntimeContext(run_id=run_id, step_id=step_id, state=state, logger=self.logger)

        start = time.monotonic()
        if self.logger:
            self.logger.info("TOOL_START", {"tool_name": tool.name, "run_id": run_id, "step_id": step_id})

        retries = tool.retries or 0
        attempt = 0
        last_error = None
        while attempt <= retries:
            attempt += 1
            try:
                if tool.timeout:
                    result = await asyncio.wait_for(tool.execute(tool_input, context), timeout=tool.timeout)
                else:
                    result = await tool.execute(tool_input, context)
                if not isinstance(result, ToolResult):
                    raise StepExecutionError("Tool must return ToolResult.")
                if not result.success:
                    raise StepExecutionError(result.error or "Tool execution failed.")
                duration_ms = int((time.monotonic() - start) * 1000)
                if self.logger:
                    self.logger.info(
                        "TOOL_SUCCESS",
                        {
                            "tool_name": tool.name,
                            "run_id": run_id,
                            "step_id": step_id,
                            "execution_time_ms": duration_ms,
                        },
                    )
                return result.output or {}, duration_ms
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt > retries:
                    if self.logger:
                        self.logger.error(
                            "TOOL_ERROR",
                            {
                                "tool_name": tool.name,
                                "run_id": run_id,
                                "step_id": step_id,
                                "execution_time_ms": int((time.monotonic() - start) * 1000),
                                "error": f"{type(exc).__name__}: {exc}",
                            },
                        )
                    raise

        raise AssertionError("unreachable: retry loop always returns or raises")

    def _resolve_next_step(self, step_def: StepDefinition, state: StateDict) -> Optional[str]:
        """Resolve next step via branch rules or sequential fallback."""
        # TODO(pain-point): Fan-Out/Fan-In - Steps currently execute sequentially.
        #   "Run this agent on each item in the list, then aggregate the results"
        #   sounds simple but needs: partial failure handling, retry of individual
        #   items, atomic result merging, and gap-tolerant aggregation.
        #   To enable parallel execution:
        #   1. Extend StepDefinition with a `parallel_group` field so adjacent
        #      steps in the same group can run concurrently via asyncio.gather.
        #   2. Build a lightweight DAG scheduler that resolves data dependencies
        #      between steps and only parallelises truly independent ones.
        #   3. Merge parallel step outputs into state atomically (snapshot per
        #      group, not per step) to preserve replay determinism.
        #   4. Update visualization to render parallel branches side-by-side.
        # TODO(roadmap): Multi-agent composition: allow a step to invoke
        #   a sub-workflow or delegate to another agent definition. This is
        #   the foundation for orchestrator-specialist agent patterns.
        if not step_def.next_rules:
            idx = self.step_order.index(step_def.step_id)
            if idx + 1 < len(self.step_order):
                return self.step_order[idx + 1]
            return None

        default_rule: Optional[NextRule] = None
        for rule in step_def.next_rules:
            if rule.is_default:
                default_rule = rule
                continue
            if rule.when is None:
                continue
            try:
                matched = safe_eval(rule.when, state)
            except (SyntaxError, ValueError) as exc:
                raise BranchResolutionError(
                    f"Invalid branch expression in step '{step_def.step_id}' "
                    f"(rule when={rule.when!r}): {exc}"
                ) from exc
            if matched:
                return rule.goto

        if default_rule is not None:
            return default_rule.goto

        raise BranchResolutionError(f"No branch matched for step: {step_def.step_id}")


def _compute_backoff_delay(attempt: int, backoff: str, initial_delay: float) -> float:
    """Compute retry delay for fixed or exponential backoff modes."""
    if attempt <= 1:
        return 0.0
    if backoff == "fixed":
        return initial_delay
    if backoff == "exponential":
        return initial_delay * (2 ** (attempt - 2))
    raise StepExecutionError(f"Unsupported backoff strategy: {backoff}")


_OUTPUT_TYPE_MAP = {
    "str": str,
    "string": str,
    "int": int,
    "integer": int,
    "float": float,
    "number": (int, float),
    "bool": bool,
    "boolean": bool,
    "list": list,
    "dict": dict,
}


def _validate_output_schema(
    step_id: str,
    output: Dict[str, Any],
    schema: Dict[str, Dict[str, Any]],
) -> None:
    """Validate output values against per-key type/enum/regex constraints.

    ``schema`` maps output key names to validation rules::

        {"severity": {"type": "str", "enum": ["P0", "P1", "P2"]},
         "summary":  {"type": "str", "regex": ".{10,}"}}

    Supported rule keys:
    - ``type``: one of str/int/float/bool/list/dict (checked with isinstance)
    - ``enum``: list of allowed values (checked with ``in``)
    - ``regex``: pattern the string value must match (``re.fullmatch``)
    """
    errors: List[str] = []
    for key, rules in schema.items():
        if key not in output:
            continue  # missing-key check is handled by output_contract
        value = output[key]

        expected_type_name = rules.get("type")
        if expected_type_name:
            expected_type = _OUTPUT_TYPE_MAP.get(expected_type_name.lower())
            if expected_type is None:
                errors.append(
                    f"key '{key}': unknown type '{expected_type_name}' in output_schema "
                    f"(valid: {', '.join(sorted(_OUTPUT_TYPE_MAP.keys()))})"
                )
            elif not isinstance(value, expected_type):
                errors.append(
                    f"key '{key}': expected type {expected_type_name}, got {type(value).__name__}"
                )

        allowed = rules.get("enum")
        if allowed is not None:
            if value not in allowed:
                errors.append(
                    f"key '{key}': value {value!r} not in allowed values {allowed}"
                )

        pattern = rules.get("regex")
        if pattern is not None:
            if not isinstance(value, str) or not _re.fullmatch(pattern, value):
                errors.append(
                    f"key '{key}': value {value!r} does not match regex {pattern!r}"
                )

    if errors:
        raise StepExecutionError(
            f"Output schema violation for step {step_id}: {'; '.join(errors)}"
        )
