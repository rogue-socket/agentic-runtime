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
import html
import json

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
    # TODO(eng): html-template - This renderer builds the entire HTML page
    #   via f-string concatenation.  This is fragile and hard to maintain
    #   as the report grows.  Consider:
    #   1. Move the HTML/CSS skeleton to a separate .html template file
    #      loaded at runtime with simple {{placeholder}} substitution.
    #   2. Or use Python's string.Template / jinja2 (lightweight) for
    #      structured templating with loops and conditionals.
    #   3. Keep the html.escape() calls for any user-supplied values to
    #      prevent XSS in the generated report.
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

    html_doc = f"""<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <title>Run Visualization - {html.escape(run_id)}</title>
  <style>
    :root {{
      --bg: #f6f8fb;
      --fg: #1f2937;
      --card: #ffffff;
      --line: #d1d5db;
      --accent: #0f766e;
      --fail: #b91c1c;
    }}
    body {{ font-family: "IBM Plex Sans", "Segoe UI", sans-serif; background: var(--bg); color: var(--fg); margin: 0; padding: 24px; }}
    h1, h2 {{ margin: 0 0 12px 0; }}
    section {{ margin: 18px 0; }}
    .card {{ background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 12px; margin-bottom: 10px; }}
    table {{ width: 100%; border-collapse: collapse; background: var(--card); border-radius: 10px; overflow: hidden; }}
    th, td {{ border: 1px solid var(--line); padding: 8px; text-align: left; font-size: 13px; }}
    th {{ background: #e5eef5; }}
    pre {{ background: #0b1020; color: #e5f3ff; padding: 10px; border-radius: 8px; overflow-x: auto; }}
    .small {{ font-size: 13px; }}
  </style>
</head>
<body>
  <h1>Run Visualization</h1>
  <p class=\"small\"><strong>Run:</strong> {html.escape(run_id)}</p>
  <section>
    <div class=\"card\">
      <h2>Run Summary</h2>
      <p><strong>Started:</strong> {run_started}</p>
      <p><strong>Completed:</strong> {run_completed}</p>
      <p><strong>Total Duration (ms):</strong> {run_duration}</p>
    </div>
  </section>

  <section>
    <h2>Execution Graph</h2>
    <div class=\"card\">
      {f'<div class="mermaid">{html.escape(mermaid_graph)}</div>' if mermaid_graph else '<p class="small">(no edges)</p>'}
      <details>
        <summary>Raw edge list</summary>
        <pre>{html.escape(chr(10).join(edge_lines) if edge_lines else '(no edges)')}</pre>
      </details>
    </div>
    <table>
      <thead><tr><th>Step</th><th>Type</th><th>Status</th><th>Attempts</th><th>Duration (ms)</th></tr></thead>
      <tbody>{''.join(graph_rows)}</tbody>
    </table>
  </section>

  <section>
    <h2>Branch Decisions</h2>
    <table>
      <thead><tr><th>Step</th><th>Condition</th><th>Result</th><th>Goto</th><th>Selected</th></tr></thead>
      <tbody>{''.join(branch_rows) if branch_rows else '<tr><td colspan="5">No branch rules evaluated.</td></tr>'}</tbody>
    </table>
  </section>

  <section>
    <h2>Step Timeline</h2>
    <table>
      <thead><tr><th>Step</th><th>Type</th><th>Status</th><th>Attempts</th><th>Duration (ms)</th><th>Call Duration (ms)</th><th>Started</th><th>Finished</th><th>Tool</th></tr></thead>
      <tbody>{''.join(timeline_rows)}</tbody>
    </table>
  <script src="../../docs/mermaid.min.js"></script>
  <script>
    if (window.mermaid) {{
      window.mermaid.initialize({{ startOnLoad: true, securityLevel: "strict", theme: "default" }});
    }}
  </script>
  </section>

  <section>
    <h2>Tool Calls</h2>
    <table>
      <thead><tr><th>Step</th><th>Tool</th><th>Arguments</th><th>Result</th><th>Latency (ms)</th></tr></thead>
      <tbody>{''.join(tool_rows) if tool_rows else '<tr><td colspan="5">No tool steps executed.</td></tr>'}</tbody>
    </table>
  </section>

  <section>
    <h2>State Timeline</h2>
    <div class=\"card\"><h3>Initial State</h3><pre>{html.escape(_pretty_json(timeline.initial_state))}</pre></div>
    {''.join(state_blocks)}
    <div class=\"card\"><h3>Latest State</h3><pre>{html.escape(_pretty_json(timeline.latest_state))}</pre></div>
  </section>
</body>
</html>
"""

    path.write_text(html_doc, encoding="utf-8")
    return str(path)


def _pretty_json(data: Any) -> str:
    """Render JSON-like object with stable formatting for HTML blocks."""
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) if data is not None else "null"


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
