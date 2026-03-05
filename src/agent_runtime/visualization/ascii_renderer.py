from __future__ import annotations

from typing import List

from .graph_builder import GraphView
from .timeline_builder import TimelineView


_STATUS_ICON = {
    "COMPLETED": "OK",
    "COMPLETED_WITH_ERRORS": "WARN",
    "FAILED": "FAIL",
    "RUNNING": "RUN",
    "PENDING": "WAIT",
    "SKIPPED": "-",
}


def render_ascii(run_id: str, graph: GraphView, timeline: TimelineView) -> str:
    lines: List[str] = []
    lines.append(f"Run: {run_id}")
    lines.append("")
    lines.append("Execution Graph")
    lines.append("start")
    for node in graph.nodes:
        icon = _STATUS_ICON.get(node.status, "?")
        duration = f"{node.duration_ms}ms" if node.duration_ms is not None else "n/a"
        attempts = f"retry {node.attempts - 1}" if node.attempts > 1 else "retry 0"
        lines.append(f" └── {node.step_id} {icon} ({duration}, {attempts})")

    if graph.branch_decisions:
        lines.append("")
        lines.append("Branch Decisions")
        for decision in graph.branch_decisions:
            selected = "selected" if decision.selected else "not-selected"
            lines.append(
                f" - {decision.step_id}: when='{decision.condition}' -> {decision.result} goto={decision.goto} ({selected})"
            )

    lines.append("")
    lines.append("Step Timeline")
    for item in timeline.steps:
        duration = f"{item.duration_ms}ms" if item.duration_ms is not None else "n/a"
        lines.append(f" - {item.step_id} ({item.step_type}) {item.status} attempts={item.attempts} duration={duration}")
        if item.tool_name:
            lines.append(f"   tool: {item.tool_name}")
        if item.error:
            lines.append(f"   error: {item.error}")
        elif item.last_error:
            lines.append(f"   last_error: {item.last_error}")

    lines.append("")
    lines.append("State Timeline")
    for item in timeline.steps:
        lines.append(f" - {item.step_id}")
        if not item.state_changes:
            lines.append("   (no changes)")
            continue
        for change in item.state_changes:
            if change.op == "+":
                lines.append(f"   + {change.path}")
            elif change.op == "-":
                lines.append(f"   - {change.path}")
            else:
                lines.append(f"   ~ {change.path}")

    return "\n".join(lines)
