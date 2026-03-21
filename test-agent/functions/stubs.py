"""Stub functions for the quickstart workflow.

The runtime discovers functions from the functions/ directory.
Any public function in a .py file can be referenced in workflow YAML
using the `type: function` step type.

Reference by qualified name: `module.function_name`
  e.g. `stubs.classify_severity` references `classify_severity`
  in `functions/stubs.py`.

Signature: (inputs: dict) -> dict
"""


def classify_severity(inputs: dict) -> dict:
    """Classify issue severity based on keywords.

    Usage in workflow YAML:
        - id: classify
          type: function
          function: stubs.classify_severity
          inputs:
            issue: inputs.issue
    """
    issue = (inputs.get("issue") or "").lower()
    if any(w in issue for w in ("outage", "down", "crash", "data loss")):
        severity = "critical"
    elif any(w in issue for w in ("error", "fail", "broken", "500")):
        severity = "high"
    elif any(w in issue for w in ("slow", "timeout", "latency")):
        severity = "medium"
    else:
        severity = "low"
    return {"severity": severity}


def format_output(inputs: dict) -> dict:
    """Formats text as a simple report."""
    text = inputs.get("text", "")
    return {"report": f"--- Report ---\n{text}\n--- End ---"}
