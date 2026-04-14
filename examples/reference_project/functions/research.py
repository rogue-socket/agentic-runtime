"""Research helper functions for the multi-agent quickstart workflow.

Used by workflows/research.yaml alongside the researcher and advisor agents.

Signature: (inputs: dict) -> dict
"""


def format_brief(inputs: dict) -> dict:
    """Combine findings and recommendation into a formatted brief."""
    findings = inputs.get("findings", "No findings")
    recommendation = inputs.get("recommendation", "No recommendation")
    brief = (
        "=== RESEARCH BRIEF ===\n\n"
        f"FINDINGS:\n{findings}\n\n"
        f"RECOMMENDATION:\n{recommendation}\n\n"
        "======================"
    )
    return {"brief": brief}


def extract_action_items(inputs: dict) -> dict:
    """Count bullet/numbered items in the findings text."""
    findings = inputs.get("findings", "")
    lines = [line.strip() for line in findings.split("\n") if line.strip()]
    count = len([
        line for line in lines
        if line and (line[0].isdigit() or line.startswith("-") or line.startswith("*"))
    ])
    return {"action_count": count, "status": "reviewed"}
