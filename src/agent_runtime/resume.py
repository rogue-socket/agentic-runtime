from __future__ import annotations

"""File: src/agent_runtime/resume.py

Purpose:
Provide resume-point resolution and resume eligibility checks.

Description:
Contains helpers used by CLI and executor resume flow to validate run
status and compute the correct next step after failure/history replay.
"""

from typing import Dict, List, Optional, Tuple

from .core import NextRule, StepDefinition, StepExecution, StepStatus
from .errors import StepExecutionError
from .utils import safe_eval


def determine_resume_step(
    workflow_steps: List[StepDefinition],
    executions: List[StepExecution],
) -> Optional[str]:
    """Compute step id from which execution should resume.

    Strategy:
    - Resume failed step directly if one exists in history.
    - If no failures, resolve next step from final executed step/branch.
    - If no executions, return first workflow step.
    """
    for execution in executions:
        if execution.status == StepStatus.FAILED:
            return execution.step_id

    if not executions:
        return workflow_steps[0].step_id if workflow_steps else None

    last_step_id = executions[-1].step_id
    step_map = {s.step_id: s for s in workflow_steps}
    if last_step_id not in step_map:
        raise StepExecutionError(f"Unknown step id in history: {last_step_id}")
    last_step = step_map[last_step_id]
    return _resolve_next_step(last_step, workflow_steps, executions[-1].state_after or {})


def _resolve_next_step(step_def: StepDefinition, workflow_steps: List[StepDefinition], state: dict) -> Optional[str]:
    """Resolve post-step next target using branch/default/sequential logic."""
    step_order = [s.step_id for s in workflow_steps]
    if not step_def.next_rules:
        idx = step_order.index(step_def.step_id)
        if idx + 1 < len(step_order):
            return step_order[idx + 1]
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

    raise StepExecutionError(f"No branch matched for step: {step_def.step_id}")


def validate_resume(run_status: str) -> None:
    """Validate that a run status is resumable.

    Raises:
        StepExecutionError: For non-failed statuses.
    """
    if run_status == StepStatus.COMPLETED or run_status == "COMPLETED_WITH_ERRORS":
        raise StepExecutionError("Cannot resume a completed run.")
    if run_status == StepStatus.RUNNING:
        raise StepExecutionError("Cannot resume a running run.")
    if run_status != StepStatus.FAILED:
        raise StepExecutionError(f"Cannot resume run with status: {run_status}")

# [TODO] Support step-level idempotency verification before resuming side-effecting steps.
# [TODO] Support retry conditions (e.g., retry only on specific error types).
