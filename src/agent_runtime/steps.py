from __future__ import annotations

from typing import Any, Callable, Dict

from .errors import HandlerNotFoundError
from .state import RuntimeState

StateDict = Dict[str, Any]
StepHandler = Callable[[RuntimeState], StateDict]


class StepHandlerRegistry:
    def __init__(self) -> None:
        self._handlers: Dict[str, StepHandler] = {}

    def register(self, name: str, handler: StepHandler) -> None:
        self._handlers[name] = handler

    def get(self, name: str) -> StepHandler:
        if name not in self._handlers:
            raise HandlerNotFoundError(f"Handler not found: {name}")
        return self._handlers[name]


def generate_summary(state: RuntimeState) -> StateDict:
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
