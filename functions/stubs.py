"""Deterministic stub functions for sample workflows and tests.

These produce predictable output without LLM calls, making them
suitable for demos, development, and integration testing.

Signature: (inputs: dict) -> dict
"""
# [Pain Point Solved] #N10 Non-Deterministic Testing Paralysis: These stubs give
#   you predictable, assertable outputs for every workflow step — so you can test
#   the orchestration, state flow, and branching logic without LLM non-determinism.


def generate_summary(inputs: dict) -> dict:
    """Produce a fixed summary from an issue description."""
    issue = inputs.get("issue", "")
    return {"summary": f"Summary of issue: {issue}"}


def classify_severity(inputs: dict) -> dict:
    """Return a fixed severity classification."""
    return {"severity": "medium", "reason": "heuristic classification"}


def diagnose_issue(inputs: dict) -> dict:
    """Produce a fixed diagnosis."""
    summary = inputs.get("summary", "")
    return {
        "analysis": f"Analysis of: {summary}",
        "root_cause": "Unknown root cause (stub)",
        "recommendation": "Investigate further",
    }


def propose_fix(inputs: dict) -> dict:
    """Propose a fixed fix."""
    return {
        "fix": "Apply standard remediation",
        "confidence": 0.5,
        "steps": ["Step 1: Investigate", "Step 2: Fix", "Step 3: Verify"],
    }


def review_code(inputs: dict) -> dict:
    """Produce a fixed code review."""
    return {
        "comments": ["No issues found (stub)"],
        "verdict": "approve",
        "summary": "Code review passed (stub)",
    }
