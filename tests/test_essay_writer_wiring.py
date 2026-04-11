from __future__ import annotations

from pathlib import Path

from agent_runtime.agent.registry import AgentRegistry
from agent_runtime.tools.discovery import discover_tools
from agent_runtime.workflow import load_workflow

ROOT = Path(__file__).resolve().parents[1]
ESSAY_ROOT = ROOT / "essay_writer"


def test_essay_writer_workflow_loads_with_function_bindings() -> None:
    """Essay workflow should resolve custom function references."""
    workflow = load_workflow(
        str(ESSAY_ROOT / "workflows" / "essay_writer.yaml"),
        functions_dir=str(ESSAY_ROOT / "functions"),
    )

    steps_by_id = {step.step_id: step for step in workflow["steps"]}

    normalize = steps_by_id["normalize_subtopics"]
    assert normalize.step_type == "function"
    assert normalize.function_ref == "essay.normalize_subtopics"
    assert normalize.function_callable is not None

    clean_title = steps_by_id["clean_title"]
    assert clean_title.step_type == "function"
    assert clean_title.function_ref == "essay.clean_title"
    assert clean_title.function_callable is not None


def test_essay_writer_agents_and_tools_are_discoverable() -> None:
    """Essay runtime dirs should expose all referenced agents/tools."""
    registry = AgentRegistry.from_directory(str(ESSAY_ROOT / "agents"))

    for agent_id in ("topic_breaker", "topic_researcher", "topic_formatter", "get_title"):
        resolved = registry.get(agent_id)
        assert resolved.agent_id == agent_id

    tools = discover_tools(str(ESSAY_ROOT / "tools"))
    assert "tools.search_online" in tools
    assert "tools.report_builder" in tools
