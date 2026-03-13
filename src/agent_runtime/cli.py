from __future__ import annotations

import argparse
import os
from typing import Any, Dict, List, Optional
import webbrowser

from .core import Executor, StepStatus
from .config import RuntimeConfig, load_config, apply_cli_overrides
from .logging import StructuredLogger
from .memory import EpisodicMemory, MemoryManager, ProceduralMemory, SemanticMemory, WorkingMemory
from .steps import StepHandlerRegistry, generate_summary, classify_severity, diagnose_issue, propose_fix, review_code
from .handler_discovery import register_discovered_handlers
from .resume import determine_resume_step, validate_resume
from .replay import RunReplayer
from .state import RuntimeState
from .storage import SQLiteStorage
from .tools import ToolRegistry
from .tools.echo import EchoTool
from .tools.discovery import register_discovered_tools
from .workflow import load_workflow, load_workflow_from_text
from .workflow_registry import WorkflowRegistry, parse_workflow_reference
from .visualization import GraphBuilder, RunLoader, TimelineBuilder, render_ascii, render_html
from .utils import sha256_json
from .agent import AgentManifest, load_agent_manifest, validate_agent, export_agent, import_agent


EXAMPLE_WORKFLOW = """workflow:
  id: example_workflow
  version: v1
inputs:
  issue:
    description: The issue text to analyze
    default: "Login API fails for invalid token"
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

EXAMPLE_HANDLER = '''"""Example handler module.

The runtime auto-discovers handlers from the handlers/ directory.

Two conventions are supported:

1. Zero-config: every public function (not starting with _) is registered
   using the function name as the handler name.

2. Explicit: define a __handlers__ dict mapping handler names to functions.
   This gives you full control over naming and lets you skip helper functions.

This file uses convention 1 (zero-config). Both functions below will be
automatically available as handlers in workflow YAML.
"""

from agent_runtime.state import RuntimeState


def example_handler(state: RuntimeState) -> dict:
    """Example handler that echoes back the input with a prefix.

    Usage in workflow YAML:
        - id: my_step
          type: model
          handler: example_handler
          inputs:
            message: inputs.message
    """
    # TODO: Replace with real logic (e.g. LLM call).
    message = state.get("message", "")
    return {"result": f"Processed: {message}"}


# --- To use explicit convention instead, uncomment below and remove the
# --- public function above:
#
# def _my_internal_helper():
#     pass
#
# def _my_handler(state):
#     return {"result": "hello"}
#
# __handlers__ = {
#     "my_handler": _my_handler,
# }
'''

EXAMPLE_TOOL = '''"""Example tool module.

The runtime auto-discovers tools from the tools/ directory.

Discovery convention: every class that implements the Tool protocol (has
``name``, ``description``, ``input_schema``, and ``execute``) and whose
class name does not start with ``_`` is instantiated and registered.

Tool protocol requirements:
  - name: str           (e.g. "tools.example")
  - description: str
  - input_schema: dict  (JSON Schema for input validation)
  - timeout: Optional[float]
  - retries: Optional[int]
  - async execute(input, context) -> ToolResult
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from agent_runtime.tools.base import RuntimeContext, ToolResult


class ExampleTool:
    """Example tool that uppercases a message.

    Usage in workflow YAML:
        - id: my_step
          type: tool
          tool: tools.example
          inputs:
            text: inputs.text
    """

    name = "tools.example"
    description = "Uppercases the provided text"
    input_schema = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
        },
    }
    timeout: Optional[float] = None
    retries: Optional[int] = None

    async def execute(
        self, input: Dict[str, Any], context: RuntimeContext
    ) -> ToolResult:
        # TODO: Replace with real tool logic (e.g. API call).
        text = input.get("text", "")
        return ToolResult(
            success=True,
            output={"text": text.upper()},
            error=None,
            metadata=None,
        )
'''

RUNTIME_YAML_TEMPLATE = """# Runtime configuration for agentic-runtime.
# CLI flags override values set here.

# SQLite database path for run persistence.
db_path: runtime.db

# Directory paths for project components.
workflows_dir: workflows
handlers_dir: handlers
tools_dir: tools

# LLM provider registry.
# API keys are resolved from environment variables — never store keys here.
# llm:
#   providers:
#     openai:
#       api_key_env: OPENAI_API_KEY
#       models:
#         gpt-4:
#           temperature: 0.2
#           max_tokens: 4096
#         gpt-4o:
#           temperature: 0.1
#           max_tokens: 8192
#     anthropic:
#       api_key_env: ANTHROPIC_API_KEY
#       models:
#         claude-3-opus:
#           temperature: 0.3
#           max_tokens: 4096
#     local:
#       api_key_env: LOCAL_LLM_KEY
#       base_url: http://localhost:8080/v1
#       models:
#         llama-3:
#           temperature: 0.5
#           max_tokens: 2048

# Logging configuration.
# logging:
#   level: info               # debug | info | warning | error
#   format: json              # json | text
"""

EXAMPLE_AGENT_MANIFEST = """# Agent manifest — the portable unit of the runtime.
# Declares everything this agent needs to run.
agent:
  id: example_agent
  version: v1
  description: "Example agent that summarizes and echoes an issue"

# The workflow this agent executes.
# TODO: Support multiple workflows with a designated entry point.
workflow: workflows/example.yaml

# Handler files this agent needs.
handlers:
  - handlers/example_handler.py

# Tool files this agent needs.
tools:
  - tools/example_tool.py

# LLM providers this agent requires (must be configured in runtime.yaml).
# providers:
#   - name: openai
#     models: [gpt-4]

# Environment variables that must be set.
# env:
#   - GITHUB_TOKEN

# Default inputs (can be overridden at run time via -i).
defaults:
  issue: "Login API fails for invalid token"
"""


def _init_project(target_dir: str) -> None:
    workflows_dir = os.path.join(target_dir, "workflows")
    handlers_dir = os.path.join(target_dir, "handlers")
    tools_dir = os.path.join(target_dir, "tools")
    agents_dir = os.path.join(target_dir, "agents")

    os.makedirs(workflows_dir, exist_ok=True)
    os.makedirs(handlers_dir, exist_ok=True)
    os.makedirs(tools_dir, exist_ok=True)
    os.makedirs(agents_dir, exist_ok=True)

    example_workflow_path = os.path.join(workflows_dir, "example.yaml")
    if not os.path.exists(example_workflow_path):
        with open(example_workflow_path, "w", encoding="utf-8") as f:
            f.write(EXAMPLE_WORKFLOW)

    example_handler_path = os.path.join(handlers_dir, "example_handler.py")
    if not os.path.exists(example_handler_path):
        with open(example_handler_path, "w", encoding="utf-8") as f:
            f.write(EXAMPLE_HANDLER)

    example_tool_path = os.path.join(tools_dir, "example_tool.py")
    if not os.path.exists(example_tool_path):
        with open(example_tool_path, "w", encoding="utf-8") as f:
            f.write(EXAMPLE_TOOL)

    example_agent_path = os.path.join(agents_dir, "example_agent.yaml")
    if not os.path.exists(example_agent_path):
        with open(example_agent_path, "w", encoding="utf-8") as f:
            f.write(EXAMPLE_AGENT_MANIFEST)

    runtime_yaml_path = os.path.join(target_dir, "runtime.yaml")
    if not os.path.exists(runtime_yaml_path):
        with open(runtime_yaml_path, "w", encoding="utf-8") as f:
            f.write(RUNTIME_YAML_TEMPLATE)


def _default_handler_registry(handlers_dir: str = "handlers") -> StepHandlerRegistry:
    """Create a handler registry with built-in handlers + discovered handlers."""
    registry = StepHandlerRegistry()

    # Built-in handlers (always available)
    registry.register("generate_summary", generate_summary)
    registry.register("classify_severity", classify_severity)
    registry.register("diagnose_issue", diagnose_issue)
    registry.register("propose_fix", propose_fix)
    registry.register("review_code", review_code)

    # Discover handlers from handlers/ directory
    register_discovered_handlers(registry, handlers_dir)

    return registry


def _default_tool_registry(tools_dir: str = "tools") -> ToolRegistry:
    """Create a tool registry with built-in tools + discovered tools."""
    registry = ToolRegistry()

    # Built-in tools (always available)
    registry.register(EchoTool())

    # Discover tools from tools/ directory
    register_discovered_tools(registry, tools_dir)

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


def _try_resolve_agent(
    ref: str,
    agents_dir: str = "agents",
) -> Optional[AgentManifest]:
    """Try to resolve *ref* as an agent id from the agents/ directory.

    Returns the manifest if found, ``None`` otherwise (falls back to workflow
    resolution).
    """
    if not os.path.isdir(agents_dir):
        return None

    # Parse optional @version
    if "@" in ref:
        agent_id, _, version = ref.partition("@")
    else:
        agent_id = ref
        version = None

    for filename in os.listdir(agents_dir):
        if not filename.endswith((".yaml", ".yml")):
            continue
        filepath = os.path.join(agents_dir, filename)
        try:
            m = load_agent_manifest(filepath)
        except Exception:
            continue
        if m.agent_id == agent_id:
            if version is None or m.version == version:
                return m
    return None


def _build_input_state(
    raw_inputs: List[str], workflow_inputs: Dict[str, Any]
) -> Dict[str, Any]:
    """Parse ``-i key=value`` pairs and validate against the workflow input schema."""
    provided: Dict[str, Any] = {}
    for item in raw_inputs:
        if "=" not in item:
            raise SystemExit(f"Invalid input format: {item!r}. Expected KEY=VALUE.")
        key, _, value = item.partition("=")
        key = key.strip()
        if not key:
            raise SystemExit(f"Invalid input: empty key in {item!r}")
        provided[key] = value

    if not workflow_inputs:
        # No declared inputs — pass through as-is.
        return provided

    declared = set(workflow_inputs.keys())
    unknown = set(provided.keys()) - declared
    if unknown:
        raise SystemExit(
            f"Unknown inputs: {', '.join(sorted(unknown))}. "
            f"Declared inputs: {', '.join(sorted(declared))}"
        )

    result: Dict[str, Any] = {}
    for name, spec in workflow_inputs.items():
        if name in provided:
            result[name] = provided[name]
        elif spec.get("default") is not None:
            result[name] = spec["default"]
        elif spec.get("required", True):
            raise SystemExit(
                f"Missing required input: {name}. Provide it with: -i {name}=VALUE"
            )
    return result


def run_cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="ai")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize a new workflow project")
    init_parser.add_argument("--path", default=".", help="Target directory")

    run_parser = subparsers.add_parser("run", help="Run a workflow")
    run_parser.add_argument("workflow", help="Workflow path or workflow_id[@version]")
    run_parser.add_argument("--db-path", default=None, help="SQLite DB path (overrides runtime.yaml)")
    run_parser.add_argument("-i", "--input", action="append", default=[],
                            metavar="KEY=VALUE",
                            help="Workflow input (repeatable, e.g. -i issue=\"bug report\")")

    inspect_parser = subparsers.add_parser("inspect", help="Inspect a run")
    inspect_parser.add_argument("run_id", help="Run ID")
    inspect_parser.add_argument("--db-path", default=None, help="SQLite DB path (overrides runtime.yaml)")
    inspect_parser.add_argument("--steps", action="store_true", help="Show step details")
    inspect_parser.add_argument("--state-history", action="store_true", help="Show state evolution per step")

    resume_parser = subparsers.add_parser("resume", help="Resume a failed run")
    resume_parser.add_argument("run_id", help="Run ID")
    resume_parser.add_argument("--db-path", default=None, help="SQLite DB path (overrides runtime.yaml)")
    resume_parser.add_argument("--workflow", help="Optional workflow YAML path to validate against stored hash")

    replay_parser = subparsers.add_parser("replay", help="Deterministically replay a run")
    replay_parser.add_argument("run_id", help="Run ID")
    replay_parser.add_argument("--db-path", default=None, help="SQLite DB path (overrides runtime.yaml)")
    replay_parser.add_argument("--step-by-step", action="store_true", help="Pause between replayed steps")
    replay_parser.add_argument("--until", help="Replay until and including this step id")
    replay_parser.add_argument("--verify-state", action="store_true", help="Verify state_before matches reconstructed state")

    state_diff_parser = subparsers.add_parser("state-diff", help="Show deep state changes per step")
    state_diff_parser.add_argument("run_id", help="Run ID")
    state_diff_parser.add_argument("--db-path", default=None, help="SQLite DB path (overrides runtime.yaml)")
    state_diff_parser.add_argument("--step", help="Optional step id filter")

    visualize_parser = subparsers.add_parser("visualize", help="Visualize run execution")
    visualize_parser.add_argument("run_id", help="Run ID")
    visualize_parser.add_argument("--db-path", default=None, help="SQLite DB path (overrides runtime.yaml)")
    visualize_parser.add_argument("--ascii", action="store_true", help="Render ASCII visualization")
    visualize_parser.add_argument("--html", action="store_true", help="Render HTML visualization")
    visualize_parser.add_argument("--timeline", action="store_true", help="Render timeline-focused text view")

    validate_parser = subparsers.add_parser("validate", help="Validate an agent manifest")
    validate_parser.add_argument("manifest", help="Path to agent.yaml manifest")

    export_parser = subparsers.add_parser("export", help="Export an agent as a portable archive")
    export_parser.add_argument("manifest", help="Path to agent.yaml manifest")
    export_parser.add_argument("-o", "--output", default=None, help="Output archive path (default: <agent_id>_<version>.tar.gz)")

    import_parser = subparsers.add_parser("import", help="Import an agent archive into the project")
    import_parser.add_argument("archive", help="Path to agent .tar.gz archive")
    import_parser.add_argument("--path", default=".", help="Project root to import into")

    list_parser = subparsers.add_parser("list", help="List available agents")
    list_parser.add_argument("--agents-dir", default="agents", help="Agents directory")

    args = parser.parse_args(argv)

    if args.command == "init":
        _init_project(args.path)
        print(f"Initialized workflow project at {os.path.abspath(args.path)}")
        return 0

    # Load runtime.yaml config with CLI overrides
    cfg = load_config()
    cfg = apply_cli_overrides(cfg, args)

    if args.command == "validate":
        manifest = load_agent_manifest(args.manifest)
        results = validate_agent(manifest, project_root=".", llm_registry=cfg.llm_registry)
        all_ok = True
        for r in results:
            icon = "\u2713" if r.ok else "\u2717"
            label = f"{r.category}: {r.name}"
            if r.ok:
                print(f"  {icon} {label}")
            else:
                print(f"  {icon} {label} \u2014 {r.message}")
                all_ok = False
        if all_ok:
            print(f"\nAgent {manifest.agent_id}@{manifest.version} is valid.")
            return 0
        else:
            print(f"\nAgent {manifest.agent_id}@{manifest.version} has validation errors.")
            return 1

    if args.command == "export":
        manifest = load_agent_manifest(args.manifest)
        output = args.output or f"{manifest.agent_id}_{manifest.version}.tar.gz"
        archive_path = export_agent(manifest, output, project_root=".")
        print(f"Exported {manifest.agent_id}@{manifest.version} -> {archive_path}")
        return 0

    if args.command == "import":
        manifest = import_agent(args.archive, project_root=args.path)
        print(f"Imported {manifest.agent_id}@{manifest.version}")
        results = validate_agent(manifest, project_root=args.path, llm_registry=cfg.llm_registry)
        failures = [r for r in results if not r.ok]
        if failures:
            print("Post-import validation warnings:")
            for r in failures:
                print(f"  \u2717 {r.category}: {r.name} \u2014 {r.message}")
        return 0

    if args.command == "list":
        agents_dir = args.agents_dir
        if not os.path.isdir(agents_dir):
            print(f"No agents directory found at: {agents_dir}")
            return 0
        found = False
        for filename in sorted(os.listdir(agents_dir)):
            if not filename.endswith((".yaml", ".yml")):
                continue
            filepath = os.path.join(agents_dir, filename)
            try:
                m = load_agent_manifest(filepath)
                desc = f" \u2014 {m.description}" if m.description else ""
                print(f"  {m.agent_id}@{m.version}{desc}")
                found = True
            except Exception:
                continue
        if not found:
            print("No agents found.")
        return 0

    if args.command == "run":
        # Try agent-aware resolution: check agents/ for a manifest matching
        # the workflow arg as an agent_id (with optional @version).
        agent_manifest = _try_resolve_agent(args.workflow)

        if agent_manifest is not None:
            handler_registry = _default_handler_registry(cfg.handlers_dir)
            workflow = _load_workflow_for_run(
                agent_manifest.workflow, handler_registry, cfg.workflows_dir,
            )
            # Merge defaults: agent defaults < CLI -i overrides
            merged_inputs = list(args.input)
            if agent_manifest.defaults:
                provided_keys = set()
                for item in args.input:
                    if "=" in item:
                        provided_keys.add(item.partition("=")[0].strip())
                for key, value in agent_manifest.defaults.items():
                    if key not in provided_keys:
                        merged_inputs.append(f"{key}={value}")
            input_state = _build_input_state(merged_inputs, workflow.get("inputs", {}))
        else:
            handler_registry = _default_handler_registry(cfg.handlers_dir)
            workflow = _load_workflow_for_run(args.workflow, handler_registry, cfg.workflows_dir)
            input_state = _build_input_state(args.input, workflow.get("inputs", {}))

        steps = workflow["steps"]

        storage = SQLiteStorage(cfg.db_path)
        logger = StructuredLogger()
        memory_manager = _default_memory_manager()
        tool_registry = _default_tool_registry(cfg.tools_dir)

        executor = Executor(
            steps=steps,
            storage=storage,
            logger=logger,
            memory_manager=memory_manager,
            tool_registry=tool_registry,
        )

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
        storage = SQLiteStorage(cfg.db_path)
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
            handler_registry = _default_handler_registry(cfg.handlers_dir)
            workflow = load_workflow_from_text(run.workflow_yaml, handler_registry)
            resume_step = determine_resume_step(workflow["steps"], steps)
            if resume_step:
                print(f"Resume point: step {resume_step}")
        if args.state_history:
            _print_state_history(steps, latest_state)
        return 0

    if args.command == "resume":
        storage = SQLiteStorage(cfg.db_path)
        run = storage.load_run(args.run_id)
        validate_resume(run.status)

        handler_registry = _default_handler_registry(cfg.handlers_dir)

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
            tool_registry=_default_tool_registry(cfg.tools_dir),
        )

        print(f"Resuming run {run.run_id} from step: {resume_step}")
        resumed = executor.resume(
            run=run,
            resume_state=state,
            start_step_id=resume_step,
            on_error=workflow.get("on_error", "fail_fast"),
            state_version=state_version,
            workflow_hash=workflow.get("workflow_hash"),
        )
        print(f"Run {resumed.run_id} status: {resumed.status}")
        return 0 if resumed.status == "COMPLETED" else 1

    if args.command == "replay":
        storage = SQLiteStorage(cfg.db_path)
        replayer = RunReplayer(storage=storage, printer=print)
        replayer.replay(
            run_id=args.run_id,
            step_by_step=args.step_by_step,
            until=args.until,
            verify_state=args.verify_state,
        )
        return 0

    if args.command == "state-diff":
        storage = SQLiteStorage(cfg.db_path)
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
        storage = SQLiteStorage(cfg.db_path)
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
