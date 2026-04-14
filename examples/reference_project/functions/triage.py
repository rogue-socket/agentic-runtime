"""Triage functions for the branching quickstart workflow.

Demonstrates deterministic classification and branching logic
without LLM calls. Used by workflows/branching_triage.yaml.

Signature: (inputs: dict) -> dict
"""


def classify_issue(inputs: dict) -> dict:
    """Classify an issue by severity based on keywords."""
    issue = (inputs.get("issue") or "").lower()
    if any(w in issue for w in ("down", "outage", "crash", "500", "data loss")):
        return {
            "severity": "critical",
            "reason": "Service impact detected",
            "summary": f"CRITICAL: {inputs.get('issue', '')}",
        }
    if any(w in issue for w in ("slow", "timeout", "latency", "401", "degraded")):
        return {
            "severity": "high",
            "reason": "Performance degradation",
            "summary": f"HIGH: {inputs.get('issue', '')}",
        }
    return {
        "severity": "low",
        "reason": "No immediate impact",
        "summary": f"LOW: {inputs.get('issue', '')}",
    }


def handle_critical(inputs: dict) -> dict:
    """Format an escalation alert for critical issues."""
    issue = inputs.get("issue", "unknown issue")
    reason = inputs.get("reason", "")
    return {
        "action": "page_oncall",
        "message": f"ESCALATION: {issue} -- {reason}. Paging on-call engineer.",
    }


def handle_normal(inputs: dict) -> dict:
    """Format a log entry for non-critical issues."""
    issue = inputs.get("issue", "unknown issue")
    severity = inputs.get("severity", "unknown")
    return {
        "action": "log_ticket",
        "message": f"Logged: {issue} (severity: {severity}). Added to backlog.",
    }
