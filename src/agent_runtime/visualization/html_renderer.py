from __future__ import annotations

from pathlib import Path
from typing import Any
import html
import json

from .graph_builder import GraphView
from .timeline_builder import TimelineView


def render_html(run_id: str, graph: GraphView, timeline: TimelineView, output_path: str) -> str:
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
        timeline_rows.append(
            "<tr>"
            f"<td>{html.escape(item.step_id)}</td>"
            f"<td>{html.escape(item.step_type)}</td>"
            f"<td>{html.escape(item.status)}</td>"
            f"<td>{item.attempts}</td>"
            f"<td>{item.duration_ms if item.duration_ms is not None else 'n/a'}</td>"
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
                f"<td>{item.duration_ms if item.duration_ms is not None else 'n/a'}</td>"
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

    # [TODO] Replace text edge list with interactive graph rendering (e.g., Mermaid) without external network dependencies.
    edge_lines = [f"{edge.source} -> {edge.target} [{edge.kind}]" for edge in graph.edges]

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
    <h2>Execution Graph</h2>
    <div class=\"card\">
      <pre>{html.escape(chr(10).join(edge_lines) if edge_lines else '(no edges)')}</pre>
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
      <thead><tr><th>Step</th><th>Type</th><th>Status</th><th>Attempts</th><th>Duration (ms)</th><th>Started</th><th>Finished</th><th>Tool</th></tr></thead>
      <tbody>{''.join(timeline_rows)}</tbody>
    </table>
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
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) if data is not None else "null"
