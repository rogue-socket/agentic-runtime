from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
import copy
import uuid

from .errors import StepExecutionError
from .logging import StructuredLogger
from .memory.base import MemoryManager
from .storage.base import Storage
from .tools.registry import ToolRegistry
from .utils import StateDict, format_template, utc_now

StepHandler = Callable[[StateDict], StateDict]


class StepStatus(str):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass
class RunState:
    data: StateDict

    def snapshot(self) -> StateDict:
        return copy.deepcopy(self.data)

    def merge(self, output: StateDict) -> None:
        if not isinstance(output, dict):
            raise TypeError("Step output must be a dict.")
        self.data.update(output)


@dataclass
class StepDefinition:
    step_id: str
    step_type: str
    handler: Optional[StepHandler] = None
    tool_name: Optional[str] = None
    raw_input: Optional[Dict[str, Any]] = None


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


@dataclass
class Run:
    run_id: str
    workflow_id: str
    status: str
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    state: RunState = field(default_factory=lambda: RunState({}))
    steps: List[StepExecution] = field(default_factory=list)


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
        self.storage = storage
        self.logger = logger
        self.memory_manager = memory_manager
        self.tool_registry = tool_registry

    def run(self, workflow_id: str, initial_state: StateDict) -> Run:
        run = Run(
            run_id=str(uuid.uuid4()),
            workflow_id=workflow_id,
            status=StepStatus.PENDING,
            created_at=utc_now().isoformat(),
            state=RunState(data=copy.deepcopy(initial_state)),
        )
        self.storage.create_run(run)

        run.status = StepStatus.RUNNING
        run.started_at = utc_now().isoformat()
        self.storage.update_run_status(run.run_id, run.status, None, started_at=run.started_at)

        state_version = 0
        self.storage.save_state(run.run_id, None, state_version, run.state.data)

        for step_def in self.steps:
            execution = StepExecution(
                step_id=step_def.step_id,
                step_type=step_def.step_type,
                status=StepStatus.RUNNING,
                started_at=utc_now().isoformat(),
            )
            run.steps.append(execution)

            try:
                snapshot = run.state.snapshot()
                self.memory_manager.hydrate_state(snapshot)
                execution.input = snapshot

                if step_def.step_type == "model":
                    if step_def.handler is None:
                        raise StepExecutionError("Missing model handler.")
                    output = step_def.handler(snapshot)
                elif step_def.step_type == "tool":
                    if not step_def.tool_name:
                        raise StepExecutionError("Missing tool name.")
                    tool = self.tool_registry.get(step_def.tool_name)
                    tool_input = format_template(step_def.raw_input or {}, snapshot)
                    output = tool(tool_input)
                else:
                    raise StepExecutionError(f"Unknown step type: {step_def.step_type}")

                if output is None or not isinstance(output, dict):
                    raise StepExecutionError("Step handler must return a dict.")

                run.state.merge(output)
                self.memory_manager.persist_state(run.state.data)

                execution.output = output
                execution.status = StepStatus.COMPLETED
            except Exception as exc:  # noqa: BLE001
                execution.status = StepStatus.FAILED
                execution.error = f"{type(exc).__name__}: {exc}"
                run.status = StepStatus.FAILED
                run.error = execution.error
                run.completed_at = utc_now().isoformat()
                self.storage.update_run_status(
                    run.run_id,
                    run.status,
                    run.error,
                    completed_at=run.completed_at,
                )
            finally:
                if execution.finished_at is None:
                    execution.finished_at = utc_now().isoformat()
                if execution.started_at and execution.finished_at:
                    start = datetime.fromisoformat(execution.started_at)
                    end = datetime.fromisoformat(execution.finished_at)
                    execution.duration_ms = int((end - start).total_seconds() * 1000)

                self.storage.append_step(run.run_id, execution)

            if execution.status == StepStatus.FAILED:
                break

            state_version += 1
            self.storage.save_state(run.run_id, execution.step_id, state_version, run.state.data)

        if run.status != StepStatus.FAILED:
            run.status = StepStatus.COMPLETED
            run.completed_at = utc_now().isoformat()
            self.storage.update_run_status(
                run.run_id,
                run.status,
                None,
                completed_at=run.completed_at,
            )

        return run
