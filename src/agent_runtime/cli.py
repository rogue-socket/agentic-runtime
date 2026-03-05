from __future__ import annotations

import argparse
import os
from typing import Any, Dict, List, Optional
import webbrowser

from .core import Executor, StepStatus
from .logging import StructuredLogger
from .memory import EpisodicMemory, MemoryManager, ProceduralMemory, SemanticMemory, WorkingMemory
from .steps import StepHandlerRegistry, generate_summary
from .resume import determine_resume_step, validate_resume
from .replay import RunReplayer
from .state import RuntimeState
from .storage import SQLiteStorage
from .tools import ToolRegistry
from .tools.echo import EchoTool
from .workflow import load_workflow, load_workflow_from_text
from .workflow_registry import WorkflowRegistry, parse_workflow_reference
from .visualization import GraphBuilder, RunLoader, TimelineBuilder, render_ascii, render_html
from .utils import sha256_json


EXAMPLE_WORKFLOW = """workflow:
  id: example_workflow
  version: v1
on_error: fail_fast
steps:
  - id: generate_summary
    type: model
    handler: generate_summary
    inputs:
      issue: inputs.issue
    retry:
      attempts: 3
      backoff: exponential
      initial_delay: 1
  - id: echo_tool
    type: tool
    tool: tools.echo
    inputs:
      message: steps.generate_summary.summary
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
    registry.register(EchoTool())
    return registry


def _default_memory_manager() -> MemoryManager:
    return MemoryManager(
        working=WorkingMemory(),
        episodic=EpisodicMemory(),
        semantic=SemanticMemory(),
        procedural=ProceduralMemory(),
    )


def _load_workflow_for_run(
    workflow_ref: str,
    handler_registry: StepHandlerRegistry,
    workflows_dir: str = "workflows",
) -> Dict[str, Any]:
    if os.path.exists(workflow_ref):
        return load_workflow(workflow_ref, handler_registry)

    ref = parse_workflow_reference(workflow_ref)
    registry = WorkflowRegistry.from_directory(workflows_dir, handler_registry)
    return registry.get(ref.workflow_id, ref.version)


def run_cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="ai")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize a new workflow project")
    init_parser.add_argument("--path", default=".", help="Target directory")

    run_parser = subparsers.add_parser("run", help="Run a workflow")
    run_parser.add_argument("workflow", help="Workflow path or workflow_id[@version]")
    run_parser.add_argument("--db-path", default="runtime.db", help="SQLite DB path")
    run_parser.add_argument("--issue", default="Login API fails for invalid token", help="Initial issue text")

    inspect_parser = subparsers.add_parser("inspect", help="Inspect a run")
    inspect_parser.add_argument("run_id", help="Run ID")
    inspect_parser.add_argument("--db-path", default="runtime.db", help="SQLite DB path")
    inspect_parser.add_argument("--steps", action="store_true", help="Show step details")
    inspect_parser.add_argument("--state-history", action="store_true", help="Show state evolution per step")

    resume_parser = subparsers.add_parser("resume", help="Resume a failed run")
    resume_parser.add_argument("run_id", help="Run ID")
    resume_parser.add_argument("--db-path", default="runtime.db", help="SQLite DB path")
    resume_parser.add_argument("--workflow", help="Optional workflow YAML path to validate against stored hash")

    replay_parser = subparsers.add_parser("replay", help="Deterministically replay a run")
    replay_parser.add_argument("run_id", help="Run ID")
    replay_parser.add_argument("--db-path", default="runtime.db", help="SQLite DB path")
    replay_parser.add_argument("--step-by-step", action="store_true", help="Pause between replayed steps")
    replay_parser.add_argument("--until", help="Replay until and including this step id")
    replay_parser.add_argument("--verify-state", action="store_true", help="Verify state_before matches reconstructed state")

    state_diff_parser = subparsers.add_parser("state-diff", help="Show deep state changes per step")
    state_diff_parser.add_argument("run_id", help="Run ID")
    state_diff_parser.add_argument("--db-path", default="runtime.db", help="SQLite DB path")
    state_diff_parser.add_argument("--step", help="Optional step id filter")

    visualize_parser = subparsers.add_parser("visualize", help="Visualize run execution")
    visualize_parser.add_argument("run_id", help="Run ID")
    visualize_parser.add_argument("--db-path", default="runtime.db", help="SQLite DB path")
    visualize_parser.add_argument("--ascii", action="store_true", help="Render ASCII visualization")
    visualize_parser.add_argument("--html", action="store_true", help="Render HTML visualization")
    visualize_parser.add_argument("--timeline", action="store_true", help="Render timeline-focused text view")

    args = parser.parse_args(argv)

    if args.command == "init":
        _init_project(args.path)
        print(f"Initialized workflow project at {os.path.abspath(args.path)}")
        return 0

    if args.command == "run":
        handler_registry = StepHandlerRegistry()
        handler_registry.register("generate_summary", generate_summary)

        workflow = _load_workflow_for_run(args.workflow, handler_registry)
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
            workflow_id=workflow["workflow_id"],
            workflow_version=workflow.get("workflow_version"),
            initial_state=input_state,
            on_error=workflow.get("on_error", "fail_fast"),
            workflow_hash=workflow.get("workflow_hash"),
            workflow_yaml=workflow.get("workflow_yaml"),
            workflow_steps=workflow.get("workflow_steps"),
            input_hash=sha256_json(input_state),
        )
        print(f"Run {run.run_id} status: {run.status}")
        return 0 if run.status == "COMPLETED" else 1

    if args.command == "inspect":
        storage = SQLiteStorage(args.db_path)
        run = storage.load_run(args.run_id)
        steps = storage.load_steps(args.run_id)
        latest_state = storage.load_latest_state(args.run_id)

        version = f"@{run.workflow_version}" if run.workflow_version else ""
        print(f"Run {run.run_id} | workflow={run.workflow_id}{version} | status={run.status}")
        if run.error:
            print(f"Error: {run.error}")
        if args.steps:
            for idx, step in enumerate(steps, start=1):
                print(f"{idx} {step.step_id}")
                print(f"status: {step.status}")
                if step.attempt_count is not None:
                    print(f"attempts: {step.attempt_count}")
                if step.output is not None:
                    print("output:")
                    print(step.output)
                if step.error is not None:
                    print("error:")
                    print(step.error)
                elif step.last_error is not None:
                    print("last_error:")
                    print(step.last_error)
                print("")
        else:
            print("Steps:")
            for idx, step in enumerate(steps, start=1):
                duration = f"{step.duration_ms}ms" if step.duration_ms is not None else "n/a"
                attempts = step.attempt_count if step.attempt_count is not None else "n/a"
                print(f"  {idx}. {step.step_id} ({step.step_type}) -> {step.status} ({duration}, attempts: {attempts})")
            print("Latest state:")
            print(latest_state)

        if run.workflow_yaml:
            handler_registry = StepHandlerRegistry()
            handler_registry.register("generate_summary", generate_summary)
            workflow = load_workflow_from_text(run.workflow_yaml, handler_registry)
            resume_step = determine_resume_step(workflow["steps"], steps)
            if resume_step:
                print(f"Resume point: step {resume_step}")
        if args.state_history:
            _print_state_history(steps, latest_state)
        return 0

    if args.command == "resume":
        storage = SQLiteStorage(args.db_path)
        run = storage.load_run(args.run_id)
        validate_resume(run.status)

        handler_registry = StepHandlerRegistry()
        handler_registry.register("generate_summary", generate_summary)

        workflow_text = run.workflow_yaml
        if workflow_text is None:
            if not args.workflow:
                raise SystemExit("Workflow YAML not stored; provide --workflow to resume.")
            workflow = load_workflow(args.workflow, handler_registry)
        else:
            workflow = load_workflow_from_text(workflow_text, handler_registry)

        if args.workflow:
            current = load_workflow(args.workflow, handler_registry)
            if run.workflow_hash and current.get("workflow_hash") != run.workflow_hash:
                raise SystemExit("Workflow hash mismatch; cannot resume.")

        if run.workflow_hash and workflow.get("workflow_hash") != run.workflow_hash:
            raise SystemExit("Stored workflow hash mismatch; cannot resume.")

        steps = storage.load_steps(args.run_id)
        resume_step = determine_resume_step(workflow["steps"], steps)
        if resume_step is None:
            raise SystemExit("No resumable step found.")

        state = storage.load_latest_state(args.run_id)
        state_version = storage.load_latest_state_version(args.run_id)

        executor = Executor(
            steps=workflow["steps"],
            storage=storage,
            logger=StructuredLogger(),
            memory_manager=_default_memory_manager(),
            tool_registry=_default_tool_registry(),
        )

        print(f"Resuming run {run.run_id} from step: {resume_step}")
        resumed = executor.resume(
            run=run,
            resume_state=state,
            start_step_id=resume_step,
            on_error=workflow.get("on_error", "fail_fast"),
            state_version=state_version,
        )
        print(f"Run {resumed.run_id} status: {resumed.status}")
        return 0 if resumed.status == "COMPLETED" else 1

    if args.command == "replay":
        storage = SQLiteStorage(args.db_path)
        replayer = RunReplayer(storage=storage, printer=print)
        replayer.replay(
            run_id=args.run_id,
            step_by_step=args.step_by_step,
            until=args.until,
            verify_state=args.verify_state,
        )
        return 0

    if args.command == "state-diff":
        storage = SQLiteStorage(args.db_path)
        run = storage.load_run(args.run_id)
        steps = storage.load_steps(args.run_id)
        if args.step:
            steps = [s for s in steps if s.step_id == args.step]
            if not steps:
                raise SystemExit(f"No steps found for step id: {args.step}")

        print(f"Run {run.run_id} state diff")
        for step in steps:
            print(f"\nStep: {step.step_id}")
            if step.state_before is None or step.state_after is None:
                print("(state diff unavailable)")
                continue
            changes = RuntimeState.diff_paths(step.state_before, step.state_after)
            if not changes:
                print("(no state changes)")
                continue
            for change in changes:
                op = change["op"]
                path = change["path"]
                if op == "+":
                    print(f"+ {path} = {change['after']}")
                elif op == "-":
                    print(f"- {path} (was {change['before']})")
                else:
                    print(f"~ {path}: {change['before']} -> {change['after']}")
        return 0

    if args.command == "visualize":
        storage = SQLiteStorage(args.db_path)
        data = RunLoader(storage).load(args.run_id)
        graph = GraphBuilder().build(data)
        timeline = TimelineBuilder().build(data)

        if args.ascii:
            print(render_ascii(args.run_id, graph, timeline))
            return 0

        if args.timeline:
            print(_render_timeline_text(args.run_id, timeline))
            return 0

        output_path = os.path.join(".runs", args.run_id, "visualization.html")
        html_path = render_html(args.run_id, graph, timeline, output_path)
        print(f"Visualization generated: {html_path}")
        if not args.html:
            try:
                webbrowser.open(f"file://{os.path.abspath(html_path)}")
            except Exception:
                print("Could not open browser automatically. Open the file manually.")
        return 0

    return 1


def main() -> None:
    raise SystemExit(run_cli())


if __name__ == "__main__":
    main()


def _diff_state(before: dict, after: dict) -> dict:
    # [TODO] Improve diff granularity beyond top-level keys.
    # [TODO] Add CLI graph visualization for branching workflows.
    return RuntimeState.diff(before, after)


def _print_state_history(steps, latest_state) -> None:
    # [TODO] Support snapshot compression for large states.
    # [TODO] Handle large state output safely (pagination or truncation).
    # [TODO] Add secret redaction for sensitive fields.
    if not steps:
        return
    initial = steps[0].state_before or latest_state
    print("\nState history:")
    print("Initial state:")
    print(initial)
    print("\n----------------------------------------")
    for idx, step in enumerate(steps, start=1):
        print(f"Step {idx} {step.step_id}")
        print(f"Status: {step.status}")
        if step.attempt_count is not None:
            print(f"Attempts: {step.attempt_count}")
        before = step.state_before or {}
        after = step.state_after or {}
        diff = _diff_state(before, after)
        print("State changes:")
        if diff["added"]:
            print(f"+ {', '.join(diff['added'])}")
        if diff["removed"]:
            print(f"- {', '.join(diff['removed'])}")
        if diff["changed"]:
            print(f"~ {', '.join(diff['changed'])}")
        if not diff["added"] and not diff["removed"] and not diff["changed"]:
            print("(no changes)")
        if step.output is not None:
            print("Output:")
            print(step.output)
        if step.state_after is not None:
            print("State after:")
            print(step.state_after)
        print("\n----------------------------------------")


def _render_timeline_text(run_id: str, timeline) -> str:
    lines = [f"Run: {run_id}", "", "State Timeline", "Initial State:", str(timeline.initial_state)]
    for item in timeline.steps:
        lines.append("\n----------------------------------------")
        lines.append(f"Step: {item.step_id}")
        lines.append(f"Status: {item.status}")
        lines.append(f"Attempts: {item.attempts}")
        duration = f"{item.duration_ms}ms" if item.duration_ms is not None else "n/a"
        lines.append(f"Duration: {duration}")
        if item.error:
            lines.append(f"Error: {item.error}")
        elif item.last_error:
            lines.append(f"Last Error: {item.last_error}")
        lines.append("State changes:")
        if not item.state_changes:
            lines.append("(no changes)")
        for change in item.state_changes:
            if change.op == "+":
                lines.append(f"+ {change.path}")
            elif change.op == "-":
                lines.append(f"- {change.path}")
            else:
                lines.append(f"~ {change.path}")
    lines.append("\n----------------------------------------")
    lines.append("Latest State:")
    lines.append(str(timeline.latest_state))
    return "\n".join(lines)
