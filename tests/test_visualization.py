from __future__ import annotations

"""File: tests/test_visualization.py

Purpose:
Validate ASCII/HTML visualization generation for executed runs.
"""

import tempfile
from pathlib import Path

from agent_runtime.core import Executor, StepDefinition, StepStatus
from agent_runtime.tools.base import RuntimeContext, ToolResult
from agent_runtime.tools.registry import ToolRegistry
from agent_runtime.visualization import GraphBuilder, RunLoader, TimelineBuilder, render_ascii, render_html
from conftest import make_storage, make_memory_manager


class EchoTool:
    name = "tools.echo"
    description = "Echo"
    input_schema = {"type": "object", "properties": {"message": {"type": "string"}}}
    timeout = None
    retries = None

    async def execute(self, input, context: RuntimeContext) -> ToolResult:
        """Function implementation."""
        return ToolResult(success=True, output={"message": input["message"]}, error=None, metadata=None)


def _generate_summary(inputs: dict) -> dict:
    """Function implementation."""
    issue = inputs.get("issue", "")
    return {"summary": f"Summary of issue: {issue}"}


def test_ascii_visualization_contains_sections() -> None:
    """Function implementation."""
    storage = make_storage()
    tools = ToolRegistry()
    tools.register(EchoTool())

    steps = [
        StepDefinition(
            step_id="generate_summary",
            step_type="function",
            function_callable=_generate_summary,
            input_spec={"issue": "inputs.issue"},
        ),
        StepDefinition(
            step_id="echo_tool",
            step_type="tool",
            tool_name="tools.echo",
            input_spec={"message": "steps.generate_summary.summary"},
        ),
    ]
    executor = Executor(steps, storage, None, make_memory_manager(), tools)
    run = executor.run(workflow_id="viz", initial_state={"issue": "Login API fails for invalid token"})
    assert run.status == StepStatus.COMPLETED

    data = RunLoader(storage).load(run.run_id)
    graph = GraphBuilder().build(data)
    timeline = TimelineBuilder().build(data)

    text = render_ascii(run.run_id, graph, timeline)
    assert "Execution Graph" in text
    assert "Step Timeline" in text
    assert "State Timeline" in text
    assert "generate_summary" in text


def test_html_visualization_writes_file() -> None:
    """Function implementation."""
    storage = make_storage()
    tools = ToolRegistry()
    tools.register(EchoTool())

    steps = [
        StepDefinition(
            step_id="generate_summary",
            step_type="function",
            function_callable=_generate_summary,
            input_spec={"issue": "inputs.issue"},
        )
    ]
    executor = Executor(steps, storage, None, make_memory_manager(), tools)
    run = executor.run(workflow_id="viz", initial_state={"issue": "Login API fails for invalid token"})

    data = RunLoader(storage).load(run.run_id)
    graph = GraphBuilder().build(data)
    timeline = TimelineBuilder().build(data)

    out_dir = Path(tempfile.mkdtemp())
    out_path = out_dir / "visualization.html"
    written = render_html(run.run_id, graph, timeline, str(out_path))

    assert Path(written).exists()
    content = Path(written).read_text(encoding="utf-8")
    assert "Run Visualization" in content
    assert "Execution Graph" in content
    assert "class=\"mermaid\"" in content
    assert "mermaid.min.js" in content
    assert "State Timeline" in content
    assert "${" not in content
