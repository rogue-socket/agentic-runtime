from __future__ import annotations

"""File: src/agent_runtime/replay.py

Purpose:
Provide deterministic replay of completed/failed runs from stored data.

Description:
`RunReplayer` reconstructs state transitions from persisted step history
without invoking handlers/tools, enabling reproducible debugging.
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional
import copy

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
# TODO(pain-point): Snapshot Testing for LLM Outputs - Replay works for
#   full runs, but there's no test-fixture pattern for it. Add a `capture_golden`
#   mode that records LLM responses as snapshots, and a `replay_golden` mode that
#   replays from those snapshots in tests — so you can validate pipeline behavior
#   against known-good LLM output without making live API calls or spending money.
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
