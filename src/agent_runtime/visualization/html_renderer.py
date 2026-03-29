from __future__ import annotations

"""File: src/agent_runtime/visualization/html_renderer.py

Purpose:
Render run visualization data into a standalone HTML report.

Description:
Builds HTML sections for graph summary, branch decisions, step timeline,
tool calls, and state timeline, then writes report to disk.
"""

from pathlib import Path
from typing import Any
from functools import lru_cache
import html
import json
from string import Template

from .graph_builder import GraphView
from .timeline_builder import TimelineView


def render_html(run_id: str, graph: GraphView, timeline: TimelineView, output_path: str) -> str:
    """Generate and write HTML visualization for a run.

    Args:
        run_id: Run identifier shown in report metadata.
        graph: Graph view model from `GraphBuilder`.
        timeline: Timeline view model from `TimelineBuilder`.
        output_path: Destination HTML file path.

    Returns:
        Absolute/relative path written to disk.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    graph_rows = []
    for node in graph.nodes:
        graph_rows.append(
            "<tr>"
            f"<td>{html.escape(node.step_id)}</td>"
            f"<td>{html.escape(node.step_type)}</td>"
            f"<td>{html.escape(node.status)}</td>"
            f"<td>{node.attempts}</td>"
            f"<td>{node.duration_ms if node.duration_ms is not None else 'n/a'}</td>"
            "</tr>"
        )

    branch_rows = []
    for decision in graph.branch_decisions:
        branch_rows.append(
            "<tr>"
            f"<td>{html.escape(decision.step_id)}</td>"
            f"<td><code>{html.escape(decision.condition)}</code></td>"
            f"<td>{decision.result}</td>"
            f"<td>{html.escape(decision.goto)}</td>"
            f"<td>{decision.selected}</td>"
            "</tr>"
        )

    timeline_rows = []
    tool_rows = []
    for item in timeline.steps:
        call_duration = item.tool_duration_ms if item.tool_duration_ms is not None else item.handler_duration_ms
        timeline_rows.append(
            "<tr>"
            f"<td>{html.escape(item.step_id)}</td>"
            f"<td>{html.escape(item.step_type)}</td>"
            f"<td>{html.escape(item.status)}</td>"
            f"<td>{item.attempts}</td>"
            f"<td>{item.duration_ms if item.duration_ms is not None else 'n/a'}</td>"
            f"<td>{call_duration if call_duration is not None else 'n/a'}</td>"
            f"<td>{html.escape(item.started_at or '')}</td>"
            f"<td>{html.escape(item.finished_at or '')}</td>"
            f"<td>{html.escape(item.tool_name or '')}</td>"
            "</tr>"
        )
        if item.step_type == "tool":
            tool_rows.append(
                "<tr>"
                f"<td>{html.escape(item.step_id)}</td>"
                f"<td>{html.escape(item.tool_name or 'unknown')}</td>"
                "<td><pre>"
                + html.escape(_pretty_json(item.input_data))
                + "</pre></td>"
                "<td><pre>"
                + html.escape(_pretty_json(item.output_data))
                + "</pre></td>"
                f"<td>{item.tool_duration_ms if item.tool_duration_ms is not None else (item.duration_ms if item.duration_ms is not None else 'n/a')}</td>"
                "</tr>"
            )

    state_blocks = []
    for item in timeline.steps:
        changes = []
        for change in item.state_changes:
            if change.op == "+":
                changes.append(f"+ {change.path}")
            elif change.op == "-":
                changes.append(f"- {change.path}")
            else:
                changes.append(f"~ {change.path}")
        if not changes:
            changes.append("(no changes)")

        state_blocks.append(
            "<div class='card'>"
            f"<h3>{html.escape(item.step_id)}</h3>"
            f"<p><strong>Status:</strong> {html.escape(item.status)} | <strong>Attempts:</strong> {item.attempts}</p>"
            "<pre>" + html.escape("\n".join(changes)) + "</pre>"
            "<details><summary>Input</summary><pre>" + html.escape(_pretty_json(item.input_data)) + "</pre></details>"
            "<details><summary>Output</summary><pre>" + html.escape(_pretty_json(item.output_data)) + "</pre></details>"
            "</div>"
        )

    mermaid_graph = _build_mermaid_flow(graph)
    edge_lines = [f"{edge.source} -> {edge.target} [{edge.kind}]" for edge in graph.edges]

    run_duration = timeline.run_duration_ms if timeline.run_duration_ms is not None else "n/a"
    run_started = html.escape(timeline.run_started_at or "n/a")
    run_completed = html.escape(timeline.run_completed_at or "n/a")

    mermaid_block = (
        f'<div class="mermaid">{html.escape(mermaid_graph)}</div>'
        if mermaid_graph
        else '<p class="small">(no edges)</p>'
    )
    edge_list = html.escape("\n".join(edge_lines) if edge_lines else "(no edges)")
    branch_rows_html = "".join(branch_rows) if branch_rows else '<tr><td colspan="5">No branch rules evaluated.</td></tr>'
    tool_rows_html = "".join(tool_rows) if tool_rows else '<tr><td colspan="5">No tool steps executed.</td></tr>'

    html_doc = _load_html_template().safe_substitute(
        run_id=html.escape(run_id),
        run_started=run_started,
        run_completed=run_completed,
        run_duration=str(run_duration),
        mermaid_block=mermaid_block,
        edge_list=edge_list,
        graph_rows="".join(graph_rows),
        branch_rows=branch_rows_html,
        timeline_rows="".join(timeline_rows),
        tool_rows=tool_rows_html,
        initial_state=html.escape(_pretty_json(timeline.initial_state)),
        state_blocks="".join(state_blocks),
        latest_state=html.escape(_pretty_json(timeline.latest_state)),
    )

    path.write_text(html_doc, encoding="utf-8")
    return str(path)


def _pretty_json(data: Any) -> str:
    """Render JSON-like object with stable formatting for HTML blocks."""
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) if data is not None else "null"


@lru_cache(maxsize=1)
def _load_html_template() -> Template:
    """Load the HTML shell from disk and cache it for repeated renders."""
    template_path = Path(__file__).with_name("templates") / "run_visualization.html"
    try:
      template_text = template_path.read_text(encoding="utf-8")
    except OSError as exc:
      raise RuntimeError(f"Visualization template not found: {template_path}") from exc
    return Template(template_text)


def _mermaid_id(step_id: str) -> str:
  """Return a Mermaid-safe node id for arbitrary step ids."""
  out = []
  for ch in step_id:
    if ch.isalnum() or ch == "_":
      out.append(ch)
    else:
      out.append("_")
  value = "".join(out).strip("_")
  return value or "step"


def _build_mermaid_flow(graph: GraphView) -> str:
  """Build Mermaid flowchart markup for interactive HTML graph rendering."""
  if not graph.edges and not graph.nodes:
    return ""

  lines = ["flowchart TD"]

  for node in graph.nodes:
    node_id = _mermaid_id(node.step_id)
    label = f"{node.step_id}\\n[{node.step_type}]\\n{node.status}"
    lines.append(f"  {node_id}[{json.dumps(label)}]")

  for edge in graph.edges:
    source = _mermaid_id(edge.source)
    target = _mermaid_id(edge.target)
    kind = edge.kind or "next"
    lines.append(f"  {source} -->|{json.dumps(kind)}| {target}")

  return "\n".join(lines)
