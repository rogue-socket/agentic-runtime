from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional
import copy

from .core import StepStatus
from .errors import ReplayDataMissingError, ReplayMismatchError, RunNotFoundError
from .storage.base import Storage


@dataclass
class ReplayResult:
    run_id: str
    final_state: Dict[str, Any]
    steps_replayed: int


class RunReplayer:
    def __init__(self, storage: Storage, printer: Callable[[str], None] = print) -> None:
        self.storage = storage
        self.printer = printer

    def replay(
        self,
        run_id: str,
        step_by_step: bool = False,
        until: Optional[str] = None,
        verify_state: bool = False,
        pause_fn: Optional[Callable[[], str]] = None,
    ) -> ReplayResult:
        try:
            run = self.storage.load_run(run_id)
        except ValueError as exc:
            raise RunNotFoundError(str(exc)) from exc

        if run.status == StepStatus.RUNNING:
            raise ReplayDataMissingError("Cannot replay RUNNING run")

        steps = self.storage.load_steps(run_id)
        if not steps:
            raise ReplayDataMissingError("Replay data missing: no step history found")

        try:
            state = copy.deepcopy(self.storage.load_initial_state(run_id))
        except ValueError as exc:
            raise ReplayDataMissingError(str(exc)) from exc

        self.printer(f"Replaying run {run_id}")
        replayed = 0

        for idx, step in enumerate(steps, start=1):
            if step.state_before is None or step.state_after is None:
                raise ReplayDataMissingError(f"Replay data missing for step: {step.step_id}")

            if verify_state and state != step.state_before:
                raise ReplayMismatchError(
                    f"State mismatch before step {step.step_id} (index {idx})"
                )

            self.printer(
                f"[{idx}] {step.step_id} ({step.step_type}) status={step.status} attempts={step.attempt_count or 1} (replayed)"
            )

            state = copy.deepcopy(step.state_after)
            replayed += 1

            if until is not None and step.step_id == until:
                break

            if step_by_step:
                if pause_fn is not None:
                    pause_fn()
                else:
                    input("Press Enter to continue...")

        self.printer("Replay complete")
        return ReplayResult(run_id=run_id, final_state=state, steps_replayed=replayed)
