from __future__ import annotations

"""File: src/agent_runtime/visualization/ascii_renderer.py

Purpose:
Render run visualization data into terminal-friendly ASCII text.

Description:
Transforms graph and timeline view models into structured sections that
summarize execution path, branch decisions, and state mutations.
"""

from typing import List

from .graph_builder import GraphView
from .timeline_builder import TimelineView


# TODO(Prod Pain Point #9 — Aggregate Observability): Visualization renders a
#   single run. In production you need success rate over time, p95 latency per
#   step across all runs, which agent fails most often, and error rate trends.
#   All the data is in SQLite — add a metrics export layer (Prometheus, Datadog,
#   or a built-in `ai dashboard` command) that aggregates across runs, not just
#   within one.
_STATUS_ICON = {
    "COMPLETED": "OK",
    "COMPLETED_WITH_ERRORS": "WARN",
    "FAILED": "FAIL",
    "RUNNING": "RUN",
    "PENDING": "WAIT",
    "SKIPPED": "-",
}


def render_ascii(run_id: str, graph: GraphView, timeline: TimelineView) -> str:
    """Render graph/timeline models as plain-text report.

    Example:
        >>> isinstance(render_ascii("r1", graph=GraphView([], [], []), timeline=TimelineView({}, [], {})), str)
        True
    """
    lines: List[str] = []
    lines.append(f"Run: {run_id}")
    if timeline.run_duration_ms is not None:
        lines.append(f"Run Duration: {timeline.run_duration_ms}ms")
    if timeline.run_started_at or timeline.run_completed_at:
        lines.append(f"Started: {timeline.run_started_at or 'n/a'}")
        lines.append(f"Completed: {timeline.run_completed_at or 'n/a'}")
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
        call_duration = item.tool_duration_ms if item.tool_duration_ms is not None else item.handler_duration_ms
        if call_duration is not None:
            lines.append(f"   call_duration: {call_duration}ms")
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
