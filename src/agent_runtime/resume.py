from __future__ import annotations

"""File: src/agent_runtime/resume.py

Purpose:
Provide resume-point resolution and resume eligibility checks.

Description:
Contains helpers used by CLI and executor resume flow to validate run
status and compute the correct next step after failure/history replay.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from .core import NextRule, StepDefinition, StepExecution, StepStatus
from .errors import StepExecutionError
from .utils import safe_eval


@dataclass(frozen=True)
class ResumePolicy:
    """Safety and eligibility controls for resume-point selection.

    Attributes:
        retry_error_types: Optional allowlist of exception class names that are
            allowed to be retried on resume (e.g. ``{"TimeoutError"}``).
            If None or empty, all error classes are eligible.
        require_idempotent_tools: If True, failed ``type: tool`` steps are only
            resumable when their tool name appears in ``idempotent_tool_names``.
        idempotent_tool_names: Tool names considered safe for re-execution when
            idempotency checks are enabled.
    """

    retry_error_types: Optional[Set[str]] = None
    require_idempotent_tools: bool = False
    idempotent_tool_names: Optional[Set[str]] = None


def determine_resume_step(
    workflow_steps: List[StepDefinition],
    executions: List[StepExecution],
    policy: Optional[ResumePolicy] = None,
) -> Optional[str]:
    """Compute step id from which execution should resume.

    Strategy:
    - Resume failed step directly if one exists in history.
    - If no failures, resolve next step from final executed step/branch.
    - If no executions, return first workflow step.
    """
    step_map = {s.step_id: s for s in workflow_steps}
    resolved_policy = policy or ResumePolicy()

    for execution in executions:
        if execution.status == StepStatus.FAILED:
            _validate_failed_step_resume(execution, step_map, resolved_policy)
            return execution.step_id

    if not executions:
        return workflow_steps[0].step_id if workflow_steps else None

    last_step_id = executions[-1].step_id
    if last_step_id not in step_map:
        raise StepExecutionError(f"Unknown step id in history: {last_step_id}")
    last_step = step_map[last_step_id]
    return _resolve_next_step(last_step, workflow_steps, executions[-1].state_after or {})


def _extract_error_type(error: Optional[str]) -> Optional[str]:
    """Extract exception class name from persisted error string.

    Stored errors are formatted as ``"<TypeName>: <message>"``.
    """
    if not error:
        return None
    prefix, sep, _ = error.partition(":")
    if not sep:
        return None
    return prefix.strip() or None


def _validate_failed_step_resume(
    failed_execution: StepExecution,
    step_map: Dict[str, StepDefinition],
    policy: ResumePolicy,
) -> None:
    """Enforce retry and idempotency policy for a failed execution step."""
    step_id = failed_execution.step_id
    if step_id not in step_map:
        raise StepExecutionError(f"Unknown step id in history: {step_id}")

    step_def = step_map[step_id]
    error_type = _extract_error_type(failed_execution.error or failed_execution.last_error)

    retry_allowlist = policy.retry_error_types or set()
    if retry_allowlist:
        if error_type is None:
            raise StepExecutionError(
                f"Cannot verify retry eligibility for step '{step_id}': missing error class."
            )
        if error_type not in retry_allowlist:
            allowed = ", ".join(sorted(retry_allowlist))
            raise StepExecutionError(
                f"Step '{step_id}' failed with '{error_type}', which is not retryable by policy "
                f"(allowed: {allowed})."
            )

    # TODO(pain-point): History-Based Idempotency Tracking - The current
    #   approach is policy-based: "refuse to retry tools not in the allowlist."
    #   This prevents accidental re-execution but doesn't track what actually
    #   happened. A real idempotency layer would: (1) record external side
    #   effects ("Slack message sent", "Jira ticket created") as part of the
    #   step execution record, (2) on resume, check whether the side effect
    #   was already completed, (3) skip the tool call if so, and (4) surface
    #   this in `ai inspect` so the developer sees "skipped: already executed."
    #   This turns resume from "safe refusal" into "smart recovery."
    if step_def.step_type == "tool" and policy.require_idempotent_tools:
        allowed_tools = policy.idempotent_tool_names or set()
        tool_name = step_def.tool_name or ""
        if not tool_name or tool_name not in allowed_tools:
            allowed = ", ".join(sorted(allowed_tools)) if allowed_tools else "(none)"
            raise StepExecutionError(
                f"Refusing to resume non-idempotent tool step '{step_id}' ({tool_name or 'unknown tool'}). "
                f"Allowed idempotent tools: {allowed}."
            )


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
    if run_status == StepStatus.COMPLETED or run_status == StepStatus.COMPLETED_WITH_ERRORS:
        raise StepExecutionError("Cannot resume a completed run.")
    if run_status == StepStatus.RUNNING:
        raise StepExecutionError("Cannot resume a running run.")
    if run_status != StepStatus.FAILED:
        raise StepExecutionError(f"Cannot resume run with status: {run_status}")

# Selective step re-execution for completed runs (fork from step N with overrides)
# is intentionally left for a dedicated rerun API.
