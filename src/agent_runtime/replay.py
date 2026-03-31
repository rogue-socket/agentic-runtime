from __future__ import annotations

"""File: src/agent_runtime/replay.py

Purpose:
Provide deterministic replay of completed/failed runs from stored data.

Description:
`RunReplayer` reconstructs state transitions from persisted step history
without invoking handlers/tools, enabling reproducible debugging.
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional
import copy
import json

from .core import StepStatus
from .errors import ReplayDataMissingError, ReplayMismatchError, RunNotFoundError
from .observability import normalize_agent_trace
from .storage.base import Storage


@dataclass
class ReplayResult:
    """Summary of replay operation outcome."""

    run_id: str
    final_state: Dict[str, Any]
    steps_replayed: int


@dataclass
class GoldenFixture:
    """Serialisable test fixture captured from a completed run."""

    run_id: str
    workflow_id: str
    initial_state: Dict[str, Any]
    steps: List[Dict[str, Any]]


# [Pain Point Solved] #8 No Reproducibility: Deterministic replay reconstructs
#   state from stored snapshots without re-executing handlers. verify_state=True
#   detects drift between stored and reconstructed state — so "it worked yesterday"
#   becomes a verifiable assertion, not a vibe.
# [Pain Point Partial] #N9 Cold-Path Amnesia: Replay can re-verify individual runs
#   including branched paths, but there is no branch-coverage tracking to warn that
#   a rarely-executed path hasn't been exercised in months.
# TODO(pain-point): Cold-Path Amnesia - Add branch-coverage tracking across
#   replays. Track which workflow branches have been exercised and warn when a
#   path hasn't been tested since the workflow YAML was last modified.
# [Pain Point Solved] Snapshot Testing for LLM Outputs - capture_golden()
#   records a run as a JSON fixture, replay_golden() re-verifies against it.
class RunReplayer:
    """Reconstruct run progression from persisted history."""

    def __init__(self, storage: Storage, printer: Callable[[str], None] = print) -> None:
        """Initialize replayer with storage backend and output callback."""
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
        """Replay a run deterministically from persisted state transitions.

        Args:
            run_id: Run identifier to replay.
            step_by_step: Pause between replayed steps.
            until: Optional step id boundary (inclusive).
            verify_state: Validate reconstructed pre-step state exactly.
            pause_fn: Optional callback used when pausing.

        Returns:
            ReplayResult with final reconstructed state and count.
        """
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
            if step.state_before is None:
                raise ReplayDataMissingError(f"Replay data missing for step: {step.step_id}")

            if verify_state and state != step.state_before:
                raise ReplayMismatchError(
                    f"State mismatch before step {step.step_id} (index {idx})"
                )

            self.printer(
                f"[{idx}] {step.step_id} ({step.step_type}) status={step.status} attempts={step.attempt_count or 1} (replayed)"
            )

            if getattr(step, "agent_trace", None):
                normalized_trace = normalize_agent_trace(step.agent_trace)
                self.printer(f"  agent_trace: {len(normalized_trace)} event(s)")
                for t_idx, turn in enumerate(normalized_trace, start=1):
                    turn_type = turn.get("type", "unknown")
                    if turn_type == "model":
                        model = turn.get("model", "")
                        text_preview = (turn.get("response_text") or "")[:120]
                        self.printer(f"    {t_idx}. [model] {model}: {text_preview}")
                    elif turn_type == "tool":
                        tool_name = turn.get("tool", "")
                        success = turn.get("success", "")
                        self.printer(f"    {t_idx}. [tool] {tool_name} -> success={success}")
                    else:
                        self.printer(f"    {t_idx}. [{turn_type}]")

            if step.state_after is not None:
                state = copy.deepcopy(step.state_after)
            # Failed steps have no state_after — state carries forward unchanged
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

    # -- Golden snapshot testing -------------------------------------------------

    def capture_golden(self, run_id: str) -> GoldenFixture:
        """Capture a completed run's state transitions as a test fixture.

        The fixture contains the initial state and each step's
        ``state_before``, ``state_after``, and ``output`` — everything
        needed to replay offline and assert determinism.
        """
        try:
            run = self.storage.load_run(run_id)
        except ValueError as exc:
            raise RunNotFoundError(str(exc)) from exc

        if run.status not in (StepStatus.COMPLETED, StepStatus.COMPLETED_WITH_ERRORS):
            raise ReplayDataMissingError(
                f"Can only capture golden from COMPLETED runs (status={run.status})"
            )

        steps = self.storage.load_steps(run_id)
        if not steps:
            raise ReplayDataMissingError("No step history found")

        try:
            initial_state = self.storage.load_initial_state(run_id)
        except ValueError as exc:
            raise ReplayDataMissingError(str(exc)) from exc

        step_records: List[Dict[str, Any]] = []
        for step in steps:
            step_records.append({
                "step_id": step.step_id,
                "step_type": step.step_type,
                "status": step.status,
                "state_before": step.state_before,
                "state_after": step.state_after,
                "output": step.output,
            })

        return GoldenFixture(
            run_id=run_id,
            workflow_id=run.workflow_id,
            initial_state=initial_state,
            steps=step_records,
        )

    @staticmethod
    def save_golden(fixture: GoldenFixture, path: str) -> None:
        """Serialise a golden fixture to a JSON file."""
        data = {
            "run_id": fixture.run_id,
            "workflow_id": fixture.workflow_id,
            "initial_state": fixture.initial_state,
            "steps": fixture.steps,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

    @staticmethod
    def load_golden(path: str) -> GoldenFixture:
        """Load a golden fixture from a JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return GoldenFixture(
            run_id=data["run_id"],
            workflow_id=data["workflow_id"],
            initial_state=data["initial_state"],
            steps=data["steps"],
        )

    @staticmethod
    def replay_golden(fixture: GoldenFixture) -> ReplayResult:
        """Replay from a golden fixture, verifying state consistency.

        Walks through the fixture's steps and checks that applying each
        step's ``state_after`` in sequence produces consistent state.
        Raises ``ReplayMismatchError`` on any divergence.
        """
        state = copy.deepcopy(fixture.initial_state)
        replayed = 0

        for idx, step_data in enumerate(fixture.steps, start=1):
            expected_before = step_data.get("state_before")
            if expected_before is not None and state != expected_before:
                raise ReplayMismatchError(
                    f"Golden state mismatch before step {step_data['step_id']} (index {idx})"
                )
            state_after = step_data.get("state_after")
            if state_after is not None:
                state = copy.deepcopy(state_after)
            replayed += 1

        return ReplayResult(
            run_id=fixture.run_id,
            final_state=state,
            steps_replayed=replayed,
        )
