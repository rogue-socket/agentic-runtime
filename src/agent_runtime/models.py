"""Run/step data models — separated from the executor for low-cost imports.

These dataclasses are the public shape of a workflow run. SDK consumers and
tooling (CLI, replay, visualization) need them without dragging in the full
``Executor`` and its dispatch dependencies. ``core.py`` re-exports each name
so existing ``from agent_runtime.core import Run`` imports keep working.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .errors import StepExecutionError
from .logging import StructuredLogger
from .state import RuntimeState
from .utils import StateDict


def _to_int(value: Any) -> int:
    """Coerce a usage value to int, defaulting to 0 for None/non-numeric."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    return 0


def normalize_token_usage(usage: Optional[Dict[str, Any]]) -> Tuple[int, int, int]:
    """Return (input, output, total) tokens from a provider-shaped usage dict.

    Handles OpenAI (``prompt_tokens``/``completion_tokens``/``total_tokens``),
    Anthropic (``input_tokens``/``output_tokens``), and Gemini
    (``promptTokenCount``/``candidatesTokenCount``/``totalTokenCount``) shapes.
    Falls back to input+output for ``total`` when the provider omits it.
    """
    if not isinstance(usage, dict):
        return (0, 0, 0)
    input_tokens = _to_int(
        usage.get("input_tokens", usage.get("prompt_tokens", usage.get("promptTokenCount", 0)))
    )
    output_tokens = _to_int(
        usage.get("output_tokens", usage.get("completion_tokens", usage.get("candidatesTokenCount", 0)))
    )
    total_tokens = _to_int(usage.get("total_tokens", usage.get("totalTokenCount", 0)))
    if total_tokens <= 0:
        total_tokens = input_tokens + output_tokens
    return (input_tokens, output_tokens, total_tokens)


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
    cost_usd: Optional[float] = None  # USD cost summed across LLM calls in this step


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

    # --- SDK accessor methods ---

    def get_output(self, step_id: str) -> Optional[Dict[str, Any]]:
        """Get the output of a completed step by ID.

        Returns ``None`` if the step has not run or produced no output.
        """
        return self.state.data.get("steps", {}).get(step_id)

    def get_input(self, key: str, default: Any = None) -> Any:
        """Get a workflow input value by key."""
        return self.state.data.get("inputs", {}).get(key, default)

    @property
    def succeeded(self) -> bool:
        """``True`` if the run completed successfully."""
        return self.status == StepStatus.COMPLETED

    @property
    def failed(self) -> bool:
        """``True`` if the run ended in failure."""
        return self.status == StepStatus.FAILED

    @property
    def outputs(self) -> Dict[str, Any]:
        """All step outputs as ``{step_id: output_dict}``."""
        return dict(self.state.data.get("steps", {}))

    @property
    def step_names(self) -> List[str]:
        """Ordered list of step IDs that executed."""
        return [s.step_id for s in self._steps]

    @property
    def total_duration_ms(self) -> Optional[int]:
        """Total run duration in milliseconds, or ``None`` if not yet complete."""
        if self.started_at and self.completed_at:
            from datetime import datetime
            start = datetime.fromisoformat(self.started_at)
            end = datetime.fromisoformat(self.completed_at)
            return int((end - start).total_seconds() * 1000)
        return None

    @property
    def total_tokens(self) -> int:
        """Sum of all token usage across all steps."""
        total = 0
        for step in self._steps:
            if step.token_usage:
                total += normalize_token_usage(step.token_usage)[2]
        return total

    @property
    def total_cost_usd(self) -> Optional[float]:
        """Sum of persisted USD cost across all steps. ``None`` if no step has a cost."""
        total: Optional[float] = None
        for step in self._steps:
            if step.cost_usd is not None:
                total = (total or 0.0) + float(step.cost_usd)
        return total
