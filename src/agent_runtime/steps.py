from __future__ import annotations

"""File: src/agent_runtime/steps.py

Purpose:
Define model-step handler registration and default scaffold handler(s).

Description:
Provides a lightweight registry mapping handler names to callables and
ships `generate_summary` as a deterministic example model handler.

Key Components:
- `StepHandlerRegistry`
- `generate_summary`

Dependencies:
- RuntimeState wrapper and error types

Inputs/Outputs:
- Input: handler names and runtime step input states
- Output: structured dict outputs written into step namespaces

Side Effects:
- None.
"""

from typing import Any, Callable, Dict

from .errors import HandlerNotFoundError
from .state import RuntimeState

StateDict = Dict[str, Any]
StepHandler = Callable[..., StateDict]


class StepHandlerRegistry:
    """Registry of named model handlers used by workflow loader/executor.

    Workflow parsing resolves handler names through this registry so
    execution can dispatch model steps without dynamic imports.

    Example:
        >>> reg = StepHandlerRegistry()
        >>> reg.register("h", lambda s: {"ok": True})
    """

    def __init__(self) -> None:
        """Initialize empty handler mapping."""
        self._handlers: Dict[str, StepHandler] = {}

    def register(self, name: str, handler: StepHandler) -> None:
        """Register or replace a handler under a name.

        Args:
            name: Workflow-facing handler identifier.
            handler: Callable taking `RuntimeState` and returning dict.

        Example:
            >>> reg = StepHandlerRegistry()
            >>> reg.register("sum", generate_summary)
        """
        self._handlers[name] = handler

    def get(self, name: str) -> StepHandler:
        """Return a registered handler by name.

        Raises:
            HandlerNotFoundError: If name is unknown.

        Example:
            >>> reg = StepHandlerRegistry(); reg.register("x", lambda s: {})
            >>> callable(reg.get("x"))
            True
        """
        if name not in self._handlers:
            raise HandlerNotFoundError(f"Handler not found: {name}")
        return self._handlers[name]


def generate_summary(state: RuntimeState) -> StateDict:
    """Generate deterministic summary text from issue input.

    This scaffold implementation intentionally avoids external model
    calls so tests and examples stay deterministic and fast.

    Args:
        state: Input state expected to contain non-empty `issue` string.

    Returns:
        Dictionary containing a single `summary` field.

    Example:
        >>> generate_summary(RuntimeState({"issue": "Login API fails for invalid token"}, enforce_structure=False))
        {'summary': 'Issue related to login api failing when invalid token.'}
        >>> generate_summary(RuntimeState({"issue": "Bug"}, enforce_structure=False))["summary"]
        'Issue related to bug.'
    """
    # [SCAFFOLD:LLM] Replace deterministic summary with model-backed generation.
    # TODO: Replace this stub with an actual LLM call (e.g. OpenAI, Anthropic).
    #   This handler currently returns a hardcoded string transformation.
    #   It needs to:
    #   1. Accept a model backend configuration (provider, model name, temperature, etc.)
    #   2. Build a prompt from the step input
    #   3. Call the model and return structured output
    #   4. Handle model errors, token limits, and retries at the handler level
    if "issue" not in state:
        raise KeyError("Missing required key: issue")
    issue = state["issue"]
    if not isinstance(issue, str) or not issue.strip():
        raise ValueError("issue must be a non-empty string")

    normalized = issue.strip().lower().replace("fails for", "failing when")
    summary = f"Issue related to {normalized}."
    return {"summary": summary}


def classify_severity(state: RuntimeState) -> StateDict:
    # TODO: Replace with LLM-backed classification.
    #   Should send issue context to a model and return a structured severity assessment.
    if "issue" not in state:
        raise KeyError("Missing required key: issue")
    issue = state["issue"]
    if not isinstance(issue, str) or not issue.strip():
        raise ValueError("issue must be a non-empty string")

    lowered = issue.strip().lower()
    if any(word in lowered for word in ["crash", "down", "outage", "critical", "data loss"]):
        severity = "critical"
        reason = "Service impact keywords detected."
    elif any(word in lowered for word in ["error", "fail", "broken", "bug", "timeout"]):
        severity = "high"
        reason = "Functional failure keywords detected."
    elif any(word in lowered for word in ["slow", "degraded", "intermittent", "flaky"]):
        severity = "medium"
        reason = "Performance or reliability keywords detected."
    else:
        severity = "low"
        reason = "No high-impact keywords detected."

    return {"severity": severity, "reason": reason}


def diagnose_issue(state: RuntimeState) -> StateDict:
    # TODO: Replace with LLM-backed diagnosis.
    #   Should analyze the issue summary and any gathered context (logs, metrics) to
    #   produce a root-cause hypothesis and recommended next steps.
    if "summary" not in state:
        raise KeyError("Missing required key: summary")
    summary = state["summary"]
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("summary must be a non-empty string")

    analysis = f"Diagnosis: The issue described as '{summary.strip()}' likely involves a configuration or integration problem."
    root_cause = "Potential root cause: misconfigured service dependency or transient upstream failure."
    recommendation = "Recommended action: verify service configuration and check upstream dependency health."

    return {
        "analysis": analysis,
        "root_cause": root_cause,
        "recommendation": recommendation,
    }


def propose_fix(state: RuntimeState) -> StateDict:
    # TODO: Replace with LLM-backed fix proposal.
    #   Should take the diagnosis and produce a concrete, actionable fix (code patch,
    #   config change, runbook steps) based on the root cause analysis.
    if "analysis" not in state:
        raise KeyError("Missing required key: analysis")
    analysis = state["analysis"]
    if not isinstance(analysis, str) or not analysis.strip():
        raise ValueError("analysis must be a non-empty string")

    fix = "Proposed fix: review and update the service configuration for the affected dependency."
    confidence = "medium"
    steps_to_fix = [
        "1. Identify the failing dependency from error logs.",
        "2. Verify connection parameters and credentials.",
        "3. Apply corrected configuration and restart the service.",
        "4. Monitor for recurrence.",
    ]

    return {
        "fix": fix,
        "confidence": confidence,
        "steps": steps_to_fix,
    }


def review_code(state: RuntimeState) -> StateDict:
    # TODO: Replace with LLM-backed code review.
    #   Should analyze a code diff and produce structured review comments with
    #   severity, line references, and suggested changes.
    if "diff" not in state:
        raise KeyError("Missing required key: diff")
    diff = state["diff"]
    if not isinstance(diff, str) or not diff.strip():
        raise ValueError("diff must be a non-empty string")

    line_count = len(diff.strip().splitlines())
    comments = [
        {
            "type": "suggestion",
            "message": "Consider adding input validation for edge cases.",
        },
        {
            "type": "nit",
            "message": "Minor: variable naming could be more descriptive.",
        },
    ]
    verdict = "approve" if line_count < 50 else "request_changes"
    summary = f"Reviewed {line_count} lines of changes."

    return {
        "comments": comments,
        "verdict": verdict,
        "summary": summary,
    }
