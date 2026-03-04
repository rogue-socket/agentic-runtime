from __future__ import annotations

import argparse
import os
from typing import Any, Dict, List, Optional

from .core import Executor
from .logging import StructuredLogger
from .memory import EpisodicMemory, MemoryManager, ProceduralMemory, SemanticMemory, WorkingMemory
from .steps import StepHandlerRegistry, generate_summary
from .storage import SQLiteStorage
from .tools import ToolRegistry
from .workflow import load_workflow
from .utils import sha256_json


EXAMPLE_WORKFLOW = """name: example_workflow
on_error: fail_fast
steps:
  - id: generate_summary
    type: model
    handler: generate_summary
    retry:
      attempts: 2
      delay_seconds: 1
  - id: echo_tool
    type: tool
    tool: tools.echo
    input:
      message: "{steps[generate_summary][summary]}"
"""


def _init_project(target_dir: str) -> None:
    workflows_dir = os.path.join(target_dir, "workflows")
    os.makedirs(workflows_dir, exist_ok=True)

    example_path = os.path.join(workflows_dir, "example.yaml")
    if not os.path.exists(example_path):
        with open(example_path, "w", encoding="utf-8") as f:
            f.write(EXAMPLE_WORKFLOW)


def _default_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()

    def echo_tool(payload: Dict[str, Any]) -> Dict[str, Any]:
        return {"tool_output": payload}

    registry.register("tools.echo", echo_tool)
    return registry


def _default_memory_manager() -> MemoryManager:
    return MemoryManager(
        working=WorkingMemory(),
        episodic=EpisodicMemory(),
        semantic=SemanticMemory(),
        procedural=ProceduralMemory(),
    )


def run_cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="ai")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize a new workflow project")
    init_parser.add_argument("--path", default=".", help="Target directory")

    run_parser = subparsers.add_parser("run", help="Run a workflow")
    run_parser.add_argument("workflow", help="Path to workflow YAML")
    run_parser.add_argument("--db-path", default="runtime.db", help="SQLite DB path")
    run_parser.add_argument("--issue", default="Login API fails for invalid token", help="Initial issue text")

    inspect_parser = subparsers.add_parser("inspect", help="Inspect a run")
    inspect_parser.add_argument("run_id", help="Run ID")
    inspect_parser.add_argument("--db-path", default="runtime.db", help="SQLite DB path")

    args = parser.parse_args(argv)

    if args.command == "init":
        _init_project(args.path)
        print(f"Initialized workflow project at {os.path.abspath(args.path)}")
        return 0

    if args.command == "run":
        handler_registry = StepHandlerRegistry()
        handler_registry.register("generate_summary", generate_summary)

        workflow = load_workflow(args.workflow, handler_registry)
        steps = workflow["steps"]

        storage = SQLiteStorage(args.db_path)
        logger = StructuredLogger()
        memory_manager = _default_memory_manager()
        tool_registry = _default_tool_registry()

        executor = Executor(
            steps=steps,
            storage=storage,
            logger=logger,
            memory_manager=memory_manager,
            tool_registry=tool_registry,
        )

        input_state = {"issue": args.issue}
        run = executor.run(
            workflow_id=workflow["name"],
            initial_state=input_state,
            on_error=workflow.get("on_error", "fail_fast"),
            workflow_hash=workflow.get("workflow_hash"),
            input_hash=sha256_json(input_state),
        )
        print(f"Run {run.run_id} status: {run.status}")
        return 0 if run.status == "COMPLETED" else 1

    if args.command == "inspect":
        storage = SQLiteStorage(args.db_path)
        run = storage.load_run(args.run_id)
        steps = storage.load_steps(args.run_id)
        latest_state = storage.load_latest_state(args.run_id)

        print(f"Run {run.run_id} | workflow={run.workflow_id} | status={run.status}")
        if run.error:
            print(f"Error: {run.error}")
        print("Steps:")
        for idx, step in enumerate(steps, start=1):
            duration = f"{step.duration_ms}ms" if step.duration_ms is not None else "n/a"
            print(f"  {idx}. {step.step_id} ({step.step_type}) -> {step.status} ({duration})")
            if step.started_at:
                print(f"     Started: {step.started_at}")
            if step.finished_at:
                print(f"     Finished: {step.finished_at}")
            if step.duration_ms is not None:
                print(f"     Duration: {step.duration_ms} ms")
            if step.attempt_number is not None:
                print(f"     Attempt number: {step.attempt_number}")
            if step.input is not None:
                print(f"     Input: {step.input}")
            if step.output is not None:
                print(f"     Output: {step.output}")
            if step.error is not None:
                print(f"     Error: {step.error}")
        print("Latest state:")
        print(latest_state)
        return 0

    return 1


def main() -> None:
    raise SystemExit(run_cli())


if __name__ == "__main__":
    main()
