from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
import copy
import uuid
import time
from types import MappingProxyType
import asyncio

from .errors import BranchResolutionError, StepExecutionError, WorkflowIntegrityError
from .logging import StructuredLogger
from .memory.base import MemoryManager
from .state import RuntimeState
from .storage.base import Storage
from .tools.base import RuntimeContext, ToolResult
from .tools.registry import ToolRegistry
from .tools.validation import validate_input
from .utils import StateDict, build_step_input, format_template, safe_eval, utc_now

StepHandler = Callable[[RuntimeState], StateDict]


class StepStatus(str):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass
class RunState:
    _data: StateDict
    _frozen: bool = False

    def __post_init__(self) -> None:
        self._runtime_state = RuntimeState(self._data, enforce_structure=True)

    def snapshot(self) -> StateDict:
        return self._runtime_state.snapshot()

    @property
    def data(self) -> StateDict:
        current = self._runtime_state.to_dict()
        return MappingProxyType(current) if self._frozen else current

    def freeze(self) -> None:
        self._frozen = True

    def runtime(self) -> RuntimeState:
        return self._runtime_state

    def set_step_output(self, step_id: str, output: StateDict) -> None:
        if self._frozen:
            raise StepExecutionError("RunState is frozen.")
        self._runtime_state.set_step_output(step_id, output, writer=step_id)


@dataclass
class StepDefinition:
    step_id: str
    step_type: str
    handler: Optional[StepHandler] = None
    tool_name: Optional[str] = None
    raw_input: Optional[Dict[str, Any]] = None
    retry: Optional["RetryPolicy"] = None
    input_spec: Optional[Dict[str, Any]] = None
    input_contract: Optional[List[str]] = None
    output_contract: Optional[List[str]] = None
    next_rules: Optional[List["NextRule"]] = None


@dataclass
class NextRule:
    when: Optional[str]
    goto: str
    is_default: bool = False


@dataclass
class RetryPolicy:
    attempts: int = 1
    backoff: str = "fixed"
    initial_delay: float = 0.0


@dataclass
class StepExecution:
    step_id: str
    step_type: str
    status: str = StepStatus.PENDING
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    input: Optional[StateDict] = None
    output: Optional[StateDict] = None
    error: Optional[str] = None
    duration_ms: Optional[int] = None
    attempt_count: Optional[int] = None
    last_error: Optional[str] = None
    state_before: Optional[StateDict] = None
    state_after: Optional[StateDict] = None
    execution_index: Optional[int] = None


@dataclass
class Run:
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
        return list(self._steps) if self._frozen else self._steps

    def add_step(self, step: StepExecution) -> None:
        if self._frozen:
            raise StepExecutionError("Run is frozen.")
        self._steps.append(step)

    def set_status(self, status: str, error: Optional[str] = None, completed_at: Optional[str] = None) -> None:
        if self._frozen:
            raise StepExecutionError("Run is frozen.")
        self.status = status
        if error is not None:
            self.error = error
        if completed_at is not None:
            self.completed_at = completed_at

    def freeze(self) -> None:
        self._frozen = True
        self.state.freeze()


class Executor:
    def __init__(
        self,
        steps: List[StepDefinition],
        storage: Storage,
        logger: Optional[StructuredLogger],
        memory_manager: MemoryManager,
        tool_registry: ToolRegistry,
    ) -> None:
        self.steps = steps
        self.step_order = [step.step_id for step in steps]
        self.step_map = {step.step_id: step for step in steps}
        self.storage = storage
        self.logger = logger
        self.memory_manager = memory_manager
        self.tool_registry = tool_registry

    def run(
        self,
        workflow_id: str,
        initial_state: StateDict,
        workflow_version: Optional[str] = None,
        on_error: str = "fail_fast",
        workflow_hash: Optional[str] = None,
        workflow_yaml: Optional[str] = None,
        workflow_steps: Optional[List[str]] = None,
        input_hash: Optional[str] = None,
    ) -> Run:
        run = Run(
            run_id=str(uuid.uuid4()),
            workflow_id=workflow_id,
            workflow_version=workflow_version,
            workflow_hash=workflow_hash,
            workflow_yaml=workflow_yaml,
            workflow_steps=workflow_steps,
            input_hash=input_hash,
            status=StepStatus.PENDING,
            created_at=utc_now().isoformat(),
            state=RunState(_data={"inputs": copy.deepcopy(initial_state), "steps": {}, "runtime": {}}),
        )
        self.storage.create_run(run)

        run.set_status(StepStatus.RUNNING)
        run.started_at = utc_now().isoformat()
        self.storage.update_run_status(run.run_id, run.status, None, started_at=run.started_at)

        state_version = 0
        self.storage.save_state(run.run_id, None, state_version, run.state.data)

        return self._execute_steps(run, start_step_id=self.step_order[0], on_error=on_error, state_version=state_version)

    def resume(
        self,
        run: Run,
        resume_state: StateDict,
        start_step_id: str,
        on_error: str,
        state_version: int,
        workflow_hash: Optional[str] = None,
    ) -> Run:
        if run.workflow_hash and workflow_hash and run.workflow_hash != workflow_hash:
            raise WorkflowIntegrityError(
                f"Workflow has been modified since original run. "
                f"Original hash: {run.workflow_hash}, current hash: {workflow_hash}. "
                f"Cannot safely resume — the workflow YAML must match the original run."
            )
        run.state = RunState(_data=copy.deepcopy(resume_state))
        run.set_status(StepStatus.RUNNING)
        if run.started_at is None:
            run.started_at = utc_now().isoformat()
        self.storage.update_run_status(run.run_id, run.status, None, started_at=run.started_at)
        return self._execute_steps(run, start_step_id=start_step_id, on_error=on_error, state_version=state_version)

    def _execute_steps(self, run: Run, start_step_id: str, on_error: str, state_version: int) -> Run:
        had_errors = False
        current_step_id: Optional[str] = start_step_id
        execution_index = self.storage.load_max_execution_index(run.run_id) + 1
        while current_step_id is not None:
            if current_step_id not in self.step_map:
                raise StepExecutionError(f"Unknown step id: {current_step_id}")
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

            try:
                max_attempts = step_def.retry.attempts if step_def.retry else 1
                backoff = step_def.retry.backoff if step_def.retry else "fixed"
                initial_delay = step_def.retry.initial_delay if step_def.retry else 0.0

                output = None
                last_error: Optional[Exception] = None
                for attempt in range(1, max_attempts + 1):
                    snapshot = run.state.snapshot()
                    self.memory_manager.hydrate_state(snapshot)
                    if step_def.input_spec is not None:
                        step_input = build_step_input(step_def.input_spec, snapshot)
                    else:
                        step_input = snapshot
                    step_input_state = RuntimeState(step_input, enforce_structure=False)
                    execution.input = copy.deepcopy(step_input_state.to_dict())
                    execution.state_before = copy.deepcopy(snapshot)
                    execution.attempt_count = attempt

                    try:
                        if step_def.step_type == "model":
                            if step_def.handler is None:
                                raise StepExecutionError("Missing model handler.")
                            output = step_def.handler(step_input_state)
                        elif step_def.step_type == "tool":
                            if not step_def.tool_name:
                                raise StepExecutionError("Missing tool name.")
                            tool = self.tool_registry.get(step_def.tool_name)
                            tool_input = step_input if step_def.input_spec is not None else format_template(step_def.raw_input or {}, snapshot)
                            output = self._execute_tool(tool, tool_input, run.run_id, step_def.step_id, snapshot)
                        else:
                            raise StepExecutionError(f"Unknown step type: {step_def.step_type}")

                        last_error = None
                        break
                    except Exception as exc:  # noqa: BLE001
                        last_error = exc
                        execution.last_error = f"{type(exc).__name__}: {exc}"
                        if attempt < max_attempts:
                            delay = _compute_backoff_delay(attempt, backoff, initial_delay)
                            if delay > 0:
                                time.sleep(delay)

                if last_error is not None:
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

                # [TODO] Enforce immutability rules:
                # - Prevent modification of "inputs"
                # - Prevent overwriting existing step outputs unless explicitly allowed
                # - Add collision validation policy
                if "inputs" in output:
                    raise StepExecutionError("Step output cannot include reserved key: inputs")
                if step_def.step_id in run.state.data.get("steps", {}):
                    raise StepExecutionError(f"Step output overwrite not allowed: {step_def.step_id}")
                run.state.set_step_output(step_def.step_id, output)
                self.memory_manager.persist_state(run.state.data)
                execution.state_after = copy.deepcopy(run.state.data)

                execution.output = output
                execution.status = StepStatus.COMPLETED
            except Exception as exc:  # noqa: BLE001
                execution.status = StepStatus.FAILED
                execution.error = f"{type(exc).__name__}: {exc}"
                if execution.last_error is None:
                    execution.last_error = execution.error
                had_errors = True
                if on_error == "fail_fast":
                    run.set_status(StepStatus.FAILED, error=execution.error, completed_at=utc_now().isoformat())
                    self.storage.update_run_status(
                        run.run_id,
                        run.status,
                        run.error,
                        completed_at=run.completed_at,
                    )
                    run.freeze()
            finally:
                if execution.finished_at is None:
                    execution.finished_at = utc_now().isoformat()
                if execution.started_at and execution.finished_at:
                    start = datetime.fromisoformat(execution.started_at)
                    end = datetime.fromisoformat(execution.finished_at)
                    execution.duration_ms = int((end - start).total_seconds() * 1000)

                self.storage.append_step(run.run_id, execution)

            if execution.status == StepStatus.FAILED and on_error == "fail_fast":
                break

            state_version += 1
            self.storage.save_state(run.run_id, execution.step_id, state_version, run.state.data)
            execution_index += 1

            current_step_id = self._resolve_next_step(step_def, run.state.data)

        if run.status != StepStatus.FAILED:
            final_status = "COMPLETED_WITH_ERRORS" if had_errors else StepStatus.COMPLETED
            run.set_status(final_status, completed_at=utc_now().isoformat())
            self.storage.update_run_status(
                run.run_id,
                run.status,
                None,
                completed_at=run.completed_at,
            )
            run.freeze()

        return run

    def _execute_tool(self, tool, tool_input: Dict[str, Any], run_id: str, step_id: str, state: StateDict) -> Dict[str, Any]:
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
                    result = asyncio.run(asyncio.wait_for(tool.execute(tool_input, context), timeout=tool.timeout))
                else:
                    result = asyncio.run(tool.execute(tool_input, context))
                if not isinstance(result, ToolResult):
                    raise StepExecutionError("Tool must return ToolResult.")
                if not result.success:
                    raise StepExecutionError(result.error or "Tool execution failed.")
                if self.logger:
                    self.logger.info(
                        "TOOL_SUCCESS",
                        {
                            "tool_name": tool.name,
                            "run_id": run_id,
                            "step_id": step_id,
                            "execution_time_ms": int((time.monotonic() - start) * 1000),
                        },
                    )
                return result.output or {}
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

    def _resolve_next_step(self, step_def: StepDefinition, state: StateDict) -> Optional[str]:
        # [TODO] Detect infinite loops caused by circular branching.
        # [TODO] Support parallel step execution when DAG scheduler is introduced.
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
    if attempt <= 1:
        return 0.0
    if backoff == "fixed":
        return initial_delay
    if backoff == "exponential":
        return initial_delay * (2 ** (attempt - 2))
    raise StepExecutionError(f"Unsupported backoff strategy: {backoff}")
