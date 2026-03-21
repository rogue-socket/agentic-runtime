"""Data pipeline functions for the pipeline quickstart workflow.

Demonstrates a chain of pure data transformations without LLM calls.
Used by workflows/data_pipeline.yaml.

Signature: (inputs: dict) -> dict
"""


def parse_csv_row(inputs: dict) -> dict:
    """Parse a comma-separated string into named fields."""
    raw = inputs.get("data", "")
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) < 3:
        parts.extend([""] * (3 - len(parts)))
    return {
        "name": parts[0],
        "value": parts[1],
        "category": parts[2],
        "field_count": len(parts),
    }


def validate_record(inputs: dict) -> dict:
    """Validate parsed fields and coerce the value to a number."""
    errors = []
    name = inputs.get("name", "")
    value = inputs.get("value", "")
    if not name:
        errors.append("name is required")
    if not value:
        errors.append("value is required")
    try:
        numeric = float(value) if value else 0.0
    except ValueError:
        errors.append(f"value \'{value}\' is not numeric")
        numeric = 0.0
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "numeric_value": numeric,
        "name": name,
    }


def transform_record(inputs: dict) -> dict:
    """Normalize the value and build a display label."""
    name = inputs.get("name", "unknown")
    value = inputs.get("numeric_value", 0)
    category = inputs.get("category", "uncategorized")
    normalized = round(value / 100, 4) if value else 0
    label = f"{name} [{category}]"
    return {"label": label, "normalized": normalized, "original": value}


def format_report(inputs: dict) -> dict:
    """Produce a formatted text report from pipeline results."""
    label = inputs.get("label", "")
    normalized = inputs.get("normalized", 0)
    original = inputs.get("original", 0)
    valid = inputs.get("valid", False)
    status = "VALID" if valid else "INVALID"
    report = (
        "--- Data Pipeline Report ---\n"
        f"  Record:     {label}\n"
        f"  Original:   {original}\n"
        f"  Normalized: {normalized}\n"
        f"  Status:     {status}\n"
        "----------------------------"
    )
    return {"report": report}
