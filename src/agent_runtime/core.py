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
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set
import copy
import uuid
import time
import asyncio

from .errors import BranchResolutionError, StepExecutionError, WorkflowIntegrityError
from .logging import StructuredLogger
from .memory.base import MemoryManager
from .observability import serialize_agent_trace
from .state import RuntimeState
from .storage.base import Storage
from .tools.base import RuntimeContext, ToolResult
from .tools.registry import ToolRegistry
from .tools.validation import validate_input
from .utils import StateDict, build_step_input, format_template, safe_eval, utc_now

# Lifecycle event callback signature.
# Receives an event name (e.g. "STEP_START") and a payload dict.
EventCallback = Callable[[str, Dict[str, Any]], None]


class StepStatus(str):
    """Canonical run/step status constants."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"
    FAILED = "FAILED"


@dataclass
class RunState:
    """Runtime wrapper around mutable run state payload."""

    _data: StateDict
    _frozen: bool = False
    _overwrite_policy: str = "warn"
    _logger: Optional[StructuredLogger] = None

    def __post_init__(self) -> None:
        """Initialize underlying `RuntimeState` wrapper."""
        self._runtime_state = RuntimeState(
            self._data,
            enforce_structure=True,
            overwrite_policy=self._overwrite_policy,
            logger=self._logger,
        )

    def snapshot(self) -> StateDict:
        """Return deep-copy state snapshot."""
        return self._runtime_state.snapshot()

    @property
    def data(self) -> StateDict:
        """Return current state dictionary (read-only proxy if frozen)."""
        current = self._runtime_state.to_dict()
        return dict(current) if self._frozen else current

    def freeze(self) -> None:
        """Mark state read-only for external mutation attempts."""
        self._frozen = True

    def unfreeze(self) -> None:
        """Allow mutation again (used by resume)."""
        self._frozen = False

    def runtime(self) -> RuntimeState:
        """Expose underlying runtime-state helper."""
        return self._runtime_state

    def set_step_output(self, step_id: str, output: StateDict) -> None:
        """Persist output under `steps.<step_id>` namespace."""
        if self._frozen:
            raise StepExecutionError("RunState is frozen.")
        self._runtime_state.set_step_output(step_id, output, writer=step_id)


# [Pain Point Solved] #8 Prompt-Data Coupling: input_contract and output_contract
#   enforce explicit schema boundaries between steps. If a prompt changes its output
#   format, the contract check catches the mismatch at runtime — not six steps later.
# [Pain Point Solved] #N1 "Almost Correct" Output: output_contract validates both
#   missing and extra keys, catching LLM responses that pass structural checks but
#   silently drop or invent fields.
@dataclass
class StepDefinition:
    """Workflow step definition normalized for execution."""

    step_id: str
    step_type: str  # "agent" | "function" | "tool"
    tool_name: Optional[str] = None
    agent_id: Optional[str] = None
    agent_version: Optional[str] = None
    function_ref: Optional[str] = None  # original dotted-path reference
    function_callable: Optional[Callable] = None  # resolved at parse time
    raw_input: Optional[Dict[str, Any]] = None
    retry: Optional["RetryPolicy"] = None
    input_spec: Optional[Dict[str, Any]] = None
    input_contract: Optional[List[str]] = None
    output_contract: Optional[List[str]] = None
    output_schema: Optional[Dict[str, Dict[str, Any]]] = None  # per-key type/enum/regex validation
    next_rules: Optional[List["NextRule"]] = None
    optional: bool = False
    default_output: Optional[Dict[str, Any]] = None
    # Step-level execution time limit declared in
    # workflow YAML as `timeout_ms: 30000`. Parsed in workflow.py and stored
    # here. The executor wraps agent/tool dispatch with:
    #   asyncio.wait_for(handler_coro, timeout=timeout_ms / 1000)
    # and raises StepExecutionError on expiry so retry/on_error applies normally.
    timeout_ms: Optional[int] = None


@dataclass
class NextRule:
    """Branch rule mapping condition to target step id."""

    when: Optional[str]
    goto: str
    is_default: bool = False


# [Pain Point Solved] #7 Retries as Afterthought: First-class per-step retry with
#   configurable attempts, backoff strategy, and initial delay — declared in YAML,
#   not bolted on with try/except + sleep loops.
@dataclass
class RetryPolicy:
    """Retry/backoff configuration for one step."""

    attempts: int = 1
    backoff: str = "fixed"
    initial_delay: float = 0.0


# [Pain Point Solved] #2 State Management Nightmare: Every step captures state_before
#   and state_after snapshots, persisted atomically to SQLite. If step 5 of 7 fails,
#   you know exactly what the state was after step 4.
# [Pain Point Solved] #4 Debugging is Blind: agent_trace, duration_ms, attempt_count,
#   and last_error give per-step observability without adding print() statements.
@dataclass
class StepExecution:
    """Persisted execution record for one step attempt lifecycle."""

    # TODO(pain-point): Latency Budgets - duration_ms tracks how long
    #   each step took, but there's no way to declare "this workflow must complete
    #   in under 5s" and fail-fast when a step exceeds its budget. Add an optional
    #   `timeout_ms` on StepDefinition and a `latency_budget_ms` on the workflow
    #   so slow steps are caught in real-time, not discovered in post-mortem.
    # [Pain Point Solved] Per-step timeout_ms is enforced via asyncio.wait_for.
    # [Pain Point Solved] Workflow-level latency_budget_ms is checked at the
    #   start of each step loop iteration in __execute_steps_loop.
    step_id: str
    step_type: str
    status: str = StepStatus.PENDING
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    input: Optional[StateDict] = None
    output: Optional[StateDict] = None
    error: Optional[str] = None
    duration_ms: Optional[int] = None
    handler_duration_ms: Optional[int] = None
    tool_duration_ms: Optional[int] = None
    agent_trace: Optional[List[Dict[str, Any]]] = None  # agent reasoning trace
    attempt_count: Optional[int] = None
    last_error: Optional[str] = None
    state_before: Optional[StateDict] = None
    state_after: Optional[StateDict] = None
    execution_index: Optional[int] = None
    token_usage: Optional[Dict[str, Any]] = None
    model_name: Optional[str] = None  # LLM model used (agent steps only)
    next_step_resolved: Optional[str] = None  # branch target after this step
    side_effects: Optional[List[Dict[str, Any]]] = None  # external actions recorded by tool steps


@dataclass
class Run:
    """Top-level run record and mutable in-memory execution aggregate."""

    run_id: str
    workflow_id: str
    workflow_version: Optional[str]
    workflow_hash: Optional[str]
    workflow_yaml: Optional[str]
    workflow_steps: Optional[List[str]]
    input_hash: Optional[str]
    status: str
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    state: RunState = field(default_factory=lambda: RunState({}))
    _steps: List[StepExecution] = field(default_factory=list, repr=False)
    _frozen: bool = field(default=False, repr=False)

    @property
    def steps(self) -> List[StepExecution]:
        """Return step list (copy when run is frozen)."""
        return list(self._steps) if self._frozen else self._steps

    def add_step(self, step: StepExecution) -> None:
        """Append step record while run is mutable."""
        if self._frozen:
            raise StepExecutionError("Run is frozen.")
        self._steps.append(step)

    def set_status(self, status: str, error: Optional[str] = None, completed_at: Optional[str] = None) -> None:
        """Update run status and optional error/terminal timestamp."""
        if self._frozen:
            raise StepExecutionError("Run is frozen.")
        self.status = status
        if error is not None:
            self.error = error
        if completed_at is not None:
            self.completed_at = completed_at

    def freeze(self) -> None:
        """Freeze run and state to prevent further mutation."""
        self._frozen = True
        self.state.freeze()

    def unfreeze(self) -> None:
        """Unfreeze run to allow mutation (used by resume)."""
        self._frozen = False
        self.state.unfreeze()


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

    def _mark_run_failed_best_effort(self, run: Run, error: str) -> Optional[Exception]:
        """Set run to FAILED and persist status without masking original failures."""
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
        if error:
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
        """
        self._ensure_no_running_loop("run_async")
        return asyncio.run(
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
        self._ensure_no_running_loop("resume_async")
        return asyncio.run(
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
                            if not step_def.agent_id:
                                raise StepExecutionError("Agent step missing agent_id.")
                            if not self.agent_registry:
                                raise StepExecutionError("AgentRegistry not configured.")
                            if not self.llm_client:
                                raise StepExecutionError("LLMClient not configured.")
                            from .agent.executor import AgentExecutor
                            from .agent.strategies import AgentContext
                            agent_def = self.agent_registry.get(
                                step_def.agent_id, step_def.agent_version
                            )
                            # Inject default model from runtime config when the
                            # agent definition doesn't specify one.
                            if not agent_def.model and self.default_model:
                                agent_def = copy.copy(agent_def)
                                agent_def.model = self.default_model
                            agent_executor = AgentExecutor(
                                self.llm_client, self.tool_registry, self.logger
                            )
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
                            call_start = time.monotonic()
                            self._emit_step_progress(
                                run_id=run.run_id,
                                step_id=step_def.step_id,
                                step_type=step_def.step_type,
                                execution_index=execution_index,
                                attempt=attempt,
                                phase="dispatch",
                                elapsed_ms=0,
                            )

                            coro = self._await_with_heartbeat(
                                agent_executor.execute(agent_def, agent_input, agent_ctx),
                                run_id=run.run_id,
                                step_id=step_def.step_id,
                                step_type=step_def.step_type,
                                execution_index=execution_index,
                                attempt=attempt,
                            )
                            if step_def.timeout_ms:
                                t_sec = float(step_def.timeout_ms) / 1000.0
                                try:
                                    agent_result = await asyncio.wait_for(coro, timeout=t_sec)
                                except asyncio.TimeoutError:
                                    self._emit_step_progress(
                                        run_id=run.run_id,
                                        step_id=step_def.step_id,
                                        step_type=step_def.step_type,
                                        execution_index=execution_index,
                                        attempt=attempt,
                                        phase="timeout",
                                        elapsed_ms=int((time.monotonic() - call_start) * 1000),
                                        error=f"Agent step timed out after {step_def.timeout_ms}ms",
                                    )
                                    raise StepExecutionError(f"Agent step timed out after {step_def.timeout_ms}ms")
                            else:
                                agent_result = await coro

                            handler_duration_ms = int((time.monotonic() - call_start) * 1000)
                            self._emit_step_progress(
                                run_id=run.run_id,
                                step_id=step_def.step_id,
                                step_type=step_def.step_type,
                                execution_index=execution_index,
                                attempt=attempt,
                                phase="complete",
                                elapsed_ms=handler_duration_ms,
                            )
                            output = agent_result.outputs
                            execution.token_usage = agent_result.token_usage
                            # Capture the model name for regression detection.
                            if agent_result.trace:
                                for _turn in reversed(agent_result.trace):
                                    if _turn.llm_response and _turn.llm_response.model:
                                        execution.model_name = _turn.llm_response.model
                                        break
                            # Store a sanitized trace for observability.
                            # serialize_agent_trace() redacts common secrets/PII.
                            # TODO(pain-point): Hallucination Guardrails -
                            #   The agent output is stored as-is. For extraction tasks,
                            #   add an optional `grounding_validator` hook that cross-
                            #   checks agent output against source input — catching
                            #   invented data before it flows into your database.
                            execution.agent_trace = serialize_agent_trace(agent_result.trace)
                        elif step_def.step_type == "function":
                            if step_def.function_callable is None:
                                raise StepExecutionError("Function step missing resolved callable.")
                            func_input = step_input if step_def.input_spec is not None else snapshot
                            if isinstance(func_input, RuntimeState):
                                func_input = func_input.to_dict()
                            call_start = time.monotonic()
                            output = step_def.function_callable(func_input)
                            handler_duration_ms = int((time.monotonic() - call_start) * 1000)
                        elif step_def.step_type == "tool":
                            if not step_def.tool_name:
                                raise StepExecutionError("Missing tool name.")
                            tool = self.tool_registry.get(step_def.tool_name)
                            tool_input = step_input if step_def.input_spec is not None else format_template(step_def.raw_input or {}, snapshot)
                            call_start = time.monotonic()
                            self._emit_step_progress(
                                run_id=run.run_id,
                                step_id=step_def.step_id,
                                step_type=step_def.step_type,
                                execution_index=execution_index,
                                attempt=attempt,
                                phase="dispatch",
                                elapsed_ms=0,
                            )
                            
                            coro = self._await_with_heartbeat(
                                self._execute_tool_async(tool, tool_input, run.run_id, step_def.step_id, snapshot),
                                run_id=run.run_id,
                                step_id=step_def.step_id,
                                step_type=step_def.step_type,
                                execution_index=execution_index,
                                attempt=attempt,
                            )
                            if step_def.timeout_ms:
                                t_sec = float(step_def.timeout_ms) / 1000.0
                                try:
                                    output, tool_duration_ms = await asyncio.wait_for(coro, timeout=t_sec)
                                except asyncio.TimeoutError:
                                    self._emit_step_progress(
                                        run_id=run.run_id,
                                        step_id=step_def.step_id,
                                        step_type=step_def.step_type,
                                        execution_index=execution_index,
                                        attempt=attempt,
                                        phase="timeout",
                                        elapsed_ms=int((time.monotonic() - call_start) * 1000),
                                        error=f"Tool step timed out after {step_def.timeout_ms}ms",
                                    )
                                    raise StepExecutionError(f"Tool step timed out after {step_def.timeout_ms}ms")
                            else:
                                output, tool_duration_ms = await coro
                            self._emit_step_progress(
                                run_id=run.run_id,
                                step_id=step_def.step_id,
                                step_type=step_def.step_type,
                                execution_index=execution_index,
                                attempt=attempt,
                                phase="complete",
                                elapsed_ms=tool_duration_ms if tool_duration_ms is not None else int((time.monotonic() - call_start) * 1000),
                            )
                        else:
                            raise StepExecutionError(f"Unknown step type: {step_def.step_type}")

                        last_error = None
                        break
                    except Exception as exc:  # noqa: BLE001
                        last_error = exc
                        execution.last_error = f"{type(exc).__name__}: {exc}"
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
                run.state.set_step_output(step_def.step_id, output)
                self.memory_manager.persist_state(run.state.data)
                execution.state_after = copy.deepcopy(run.state.data)

                # Extract side-effect declarations from tool output.
                _side_effects = output.pop("__side_effects__", None)
                if isinstance(_side_effects, list):
                    execution.side_effects = _side_effects

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
                execution.error = f"{type(exc).__name__}: {exc}"
                if execution.last_error is None:
                    execution.last_error = execution.error
                had_errors = True
                if on_error == "fail_fast":
                    run.set_status(StepStatus.FAILED, error=execution.error, completed_at=utc_now().isoformat())
            finally:
                if execution.finished_at is None:
                    execution.finished_at = utc_now().isoformat()
                if execution.started_at and execution.finished_at:
                    start = datetime.fromisoformat(execution.started_at)
                    end = datetime.fromisoformat(execution.finished_at)
                    execution.duration_ms = int((end - start).total_seconds() * 1000)

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
        except Exception:
            pass  # best-effort; don't fail the run for memory persistence
        finally:
            run.freeze()

        self._emit("RUN_COMPLETE", {
            "run_id": run.run_id,
            "status": run.status,
            "error": run.error,
        })

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

        raise StepExecutionError(f"Tool execution failed: {last_error}")

    @staticmethod
    def _ensure_no_running_loop(async_entrypoint: str) -> None:
        """Raise when called from an existing event loop.

        TODO(eng): Provide an opt-in helper to run sync APIs in async contexts by
        dispatching to a dedicated worker thread if we ever need that behavior.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        raise RuntimeError(f"Detected running event loop. Use `{async_entrypoint}()` instead.")

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
            if safe_eval(rule.when, state):
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


import re as _re

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
            if expected_type and not isinstance(value, expected_type):
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
