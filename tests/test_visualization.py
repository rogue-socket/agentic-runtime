from __future__ import annotations

import tempfile
from pathlib import Path

from agent_runtime.core import Executor, StepDefinition, StepStatus
from agent_runtime.memory.base import MemoryManager
from agent_runtime.memory.episodic import EpisodicMemory
from agent_runtime.memory.procedural import ProceduralMemory
from agent_runtime.memory.semantic import SemanticMemory
from agent_runtime.memory.working import WorkingMemory
from agent_runtime.storage.sqlite import SQLiteStorage
from agent_runtime.steps import generate_summary
from agent_runtime.tools.base import RuntimeContext, ToolResult
from agent_runtime.tools.registry import ToolRegistry
from agent_runtime.visualization import GraphBuilder, RunLoader, TimelineBuilder, render_ascii, render_html


class EchoTool:
    name = "tools.echo"
    description = "Echo"
    input_schema = {"type": "object", "properties": {"message": {"type": "string"}}}
    timeout = None
    retries = None

    async def execute(self, input, context: RuntimeContext) -> ToolResult:
        return ToolResult(success=True, output={"message": input["message"]}, error=None, metadata=None)


def _storage() -> SQLiteStorage:
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.close()
    return SQLiteStorage(tmp.name)


def _memory_manager() -> MemoryManager:
    return MemoryManager(
        working=WorkingMemory(),
        episodic=EpisodicMemory(),
        semantic=SemanticMemory(),
        procedural=ProceduralMemory(),
    )


def test_ascii_visualization_contains_sections() -> None:
    storage = _storage()
    tools = ToolRegistry()
    tools.register(EchoTool())

    steps = [
        StepDefinition(
            step_id="generate_summary",
            step_type="model",
            handler=generate_summary,
            input_spec={"issue": "inputs.issue"},
        ),
        StepDefinition(
            step_id="echo_tool",
            step_type="tool",
            tool_name="tools.echo",
            input_spec={"message": "steps.generate_summary.summary"},
        ),
    ]
    executor = Executor(steps, storage, None, _memory_manager(), tools)
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
    storage = _storage()
    tools = ToolRegistry()
    tools.register(EchoTool())

    steps = [
        StepDefinition(
            step_id="generate_summary",
            step_type="model",
            handler=generate_summary,
            input_spec={"issue": "inputs.issue"},
        )
    ]
    executor = Executor(steps, storage, None, _memory_manager(), tools)
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
    assert "State Timeline" in content
