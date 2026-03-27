from __future__ import annotations

from pathlib import Path

import pytest

from agent_runtime.agent.registry import AgentRegistry
from agent_runtime.core import Executor, StepStatus
from agent_runtime.tools.echo import EchoTool
from agent_runtime.tools.registry import ToolRegistry
from agent_runtime.workflow import load_workflow
from conftest import make_memory_manager, make_storage

ROOT = Path(__file__).resolve().parents[1]

WORKFLOW_SOURCES = (
    (ROOT / "workflows", ROOT / "functions", ROOT / "agents"),
    (ROOT / "agent-one" / "workflows", ROOT / "agent-one" / "functions", ROOT / "agent-one" / "agents"),
    (ROOT / "test-agent" / "workflows", ROOT / "test-agent" / "functions", ROOT / "test-agent" / "agents"),
)


def _all_workflow_specs() -> list[tuple[Path, Path, Path]]:
    specs: list[tuple[Path, Path, Path]] = []
    for workflows_dir, functions_dir, agents_dir in WORKFLOW_SOURCES:
        for workflow_path in sorted(workflows_dir.rglob("*.yaml")):
            specs.append((workflow_path, functions_dir, agents_dir))
    return specs


ALL_WORKFLOW_SPECS = _all_workflow_specs()


def _initial_state_from_workflow(workflow: dict) -> dict:
    """Build runnable initial_state from workflow input declarations."""
    initial_state: dict = {}
    for name, spec in workflow.get("inputs", {}).items():
        if isinstance(spec, dict):
            if "default" in spec:
                initial_state[name] = spec.get("default")
            elif spec.get("required", False):
                initial_state[name] = f"test_{name}"
    return initial_state


@pytest.mark.parametrize(
    "workflow_path,functions_dir,agents_dir",
    ALL_WORKFLOW_SPECS,
    ids=[str(path.relative_to(ROOT)) for path, _, _ in ALL_WORKFLOW_SPECS],
)
def test_all_workflow_files_parse_and_agent_refs_resolve(
    workflow_path: Path,
    functions_dir: Path,
    agents_dir: Path,
) -> None:
    workflow = load_workflow(str(workflow_path), functions_dir=str(functions_dir))

    assert workflow["workflow_id"]
    assert workflow["workflow_version"]

    registry = AgentRegistry.from_directory(str(agents_dir))
    for step in workflow["steps"]:
        if step.step_type != "agent":
            continue
        resolved = registry.get(step.agent_id, step.agent_version)
        assert resolved.agent_id == step.agent_id


# Non-agent workflows can run deterministically without provider credentials.
EXECUTABLE_NO_LLM_CASES = [
    ("workflows/branching_triage.yaml", StepStatus.COMPLETED),
    ("workflows/data_pipeline.yaml", StepStatus.COMPLETED),
    ("workflows/samples/01_linear_issue_summary.yaml", StepStatus.COMPLETED),
    ("workflows/samples/02_retry_and_backoff.yaml", StepStatus.COMPLETED),
    ("workflows/samples/03_branching_triage.yaml", StepStatus.COMPLETED),
    ("workflows/samples/04_fail_and_resume.yaml", StepStatus.FAILED),
    ("workflows/samples/versioning/code_review_agent_v1.yaml", StepStatus.COMPLETED),
    ("workflows/samples/versioning/code_review_agent_v2.yaml", StepStatus.COMPLETED),
    ("agent-one/workflows/branching_triage.yaml", StepStatus.COMPLETED),
    ("agent-one/workflows/data_pipeline.yaml", StepStatus.COMPLETED),
    ("test-agent/workflows/branching_triage.yaml", StepStatus.COMPLETED),
    ("test-agent/workflows/data_pipeline.yaml", StepStatus.COMPLETED),
]


@pytest.mark.parametrize(
    "workflow_rel_path,expected_status",
    EXECUTABLE_NO_LLM_CASES,
    ids=[case[0] for case in EXECUTABLE_NO_LLM_CASES],
)
def test_no_llm_workflows_execute(
    workflow_rel_path: str,
    expected_status: str,
) -> None:
    workflow_path = ROOT / workflow_rel_path

    if workflow_rel_path.startswith("agent-one/"):
        functions_dir = ROOT / "agent-one" / "functions"
    elif workflow_rel_path.startswith("test-agent/"):
        functions_dir = ROOT / "test-agent" / "functions"
    else:
        functions_dir = ROOT / "functions"

    workflow = load_workflow(str(workflow_path), functions_dir=str(functions_dir))

    tool_registry = ToolRegistry()
    tool_registry.register(EchoTool())

    executor = Executor(
        steps=workflow["steps"],
        storage=make_storage(),
        logger=None,
        memory_manager=make_memory_manager(),
        tool_registry=tool_registry,
    )

    run = executor.run(
        workflow_id=workflow["workflow_id"],
        initial_state=_initial_state_from_workflow(workflow),
        workflow_version=workflow.get("workflow_version"),
        on_error=workflow.get("on_error", "fail_fast"),
        workflow_hash=workflow.get("workflow_hash"),
        workflow_yaml=workflow.get("workflow_yaml"),
        workflow_steps=workflow.get("workflow_steps"),
    )

    assert run.status == expected_status, run.error
    if expected_status == StepStatus.FAILED:
        assert run.error is not None
