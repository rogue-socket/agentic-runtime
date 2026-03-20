"""Sample functions for workflow function steps.

Each function has the signature: (inputs: dict) -> dict
"""


def format_markdown(inputs: dict) -> dict:
    """Wrap text in a markdown report structure."""
    text = inputs.get("text", "")
    report = f"# Report\n\n{text}\n"
    return {"report": report}


def uppercase(inputs: dict) -> dict:
    """Convert text to uppercase."""
    text = inputs.get("text", "")
    return {"text": text.upper()}
