from __future__ import annotations

"""File: src/agent_runtime/cli.py

Purpose:
Implement `ai` command-line interface for runtime operations.

Description:
Defines command parsing and handlers for project init, run, inspect,
resume, replay, state diff, and visualization commands.

Key Components:
- `run_cli` command dispatcher
- helper registries for default tool/memory setup
- inspect/state-history rendering helpers

Dependencies:
- Core executor/runtime modules, SQLite storage, visualization builders

Inputs/Outputs:
- Input: CLI args and workflow references
- Output: console reports, exit codes, and persisted run artifacts

Side Effects:
- Creates files/directories, writes DB rows, may open browser.

TODO(ux): ICP is solo dev / small team building an agent. The CLI
  experience should optimize for that persona:
  - `ai init` should scaffold a working LLM-powered agent out of the box,
    not just empty directories. Include a sample that calls a real LLM.
  - `ai run` output should show a concise progress summary by default
    (step name + status + duration), not just silence until completion.
  - Add `ai quickstart` command that creates a minimal agent, runs it,
    and opens the HTML visualization — a single-command "wow" moment.
"""

import argparse
import os
import re
import sys
from typing import Any, Dict, List, Optional
import webbrowser
import yaml

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
from .tools.http import HttpTool
from .tools.file import FileTool
from .tools.shell import ShellTool
from .tools.discovery import register_discovered_tools
from .errors import WorkflowValidationError
from .workflow import load_workflow, load_workflow_from_text
from .workflow_registry import WorkflowRegistry, parse_workflow_reference
from .visualization import GraphBuilder, RunLoader, TimelineBuilder, render_ascii, render_html
from .utils import sha256_json
from .agent import AgentManifest, load_agent_manifest, validate_agent, export_agent, import_agent
from .llm import LLMClient
from .llm.handler import make_llm_handler

_SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|secret|token|password|credential|auth|bearer)",
    re.IGNORECASE,
)


def _redact(obj: Any) -> Any:
    """Recursively redact values whose keys look like secrets."""
    if isinstance(obj, dict):
        return {
            k: ("***REDACTED***" if _SECRET_KEY_RE.search(k) else _redact(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact(item) for item in obj]
    return obj


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
# Uncomment and edit sections as needed.

# ─── Storage ──────────────────────────────────────────────────────────
# SQLite database path for run persistence.
db_path: runtime.db

# ─── Directory paths ──────────────────────────────────────────────────
workflows_dir: workflows
handlers_dir: handlers
tools_dir: tools

# ─── State overwrite policy ───────────────────────────────────────────
# Controls what happens when a step overwrites an existing state key.
#   warn   - log a structured warning (default)
#   strict - raise an error and fail the step
#   allow  - silently allow overwrites
# overwrite_policy: warn

# ─── LLM providers ───────────────────────────────────────────────────
# API keys are resolved from environment variables — never store keys here.
# Uncomment and configure providers you intend to use.
#
# default_llm_provider: openai    # used when model has no provider/ prefix
#
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

# ─── Memory ───────────────────────────────────────────────────────────
# Working memory: ephemeral per-run scratch space.
# memory:
#   working:
#     max_entries: 50            # sliding window size for context entries
#     max_scratch_bytes: 256000  # byte budget for scratch key-value store

# ─── Shell tool restrictions ──────────────────────────────────────────
# Regex patterns matched against the first token (program name) of commands.
# Denylist is checked first.
# shell:
#   allowlist:
#     - python
#     - git
#     - npm
#   denylist:
#     - rm
#     - sudo
#     - chmod

# ─── Logging ──────────────────────────────────────────────────────────
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
    """Create workflow scaffold files in target directory."""
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


def _default_handler_registry(
    handlers_dir: str = "handlers",
    llm_client: Optional[LLMClient] = None,
) -> StepHandlerRegistry:
    """Create a handler registry with built-in handlers + discovered handlers."""
    registry = StepHandlerRegistry()

    # Built-in handlers (always available)
    registry.register("generate_summary", generate_summary)
    registry.register("classify_severity", classify_severity)
    registry.register("diagnose_issue", diagnose_issue)
    registry.register("propose_fix", propose_fix)
    registry.register("review_code", review_code)
    if llm_client is not None:
        registry.register("llm", make_llm_handler(llm_client))

    # Discover handlers from handlers/ directory
    register_discovered_handlers(registry, handlers_dir)

    return registry


def _default_tool_registry(
    tools_dir: str = "tools",
    shell_allowlist: Optional[list] = None,
    shell_denylist: Optional[list] = None,
) -> ToolRegistry:
    """Create a tool registry with built-in tools + discovered tools."""
    registry = ToolRegistry()

    # Built-in tools (always available)
    registry.register(EchoTool())
    registry.register(HttpTool())
    registry.register(FileTool())
    registry.register(ShellTool(
        allowlist=shell_allowlist or None,
        denylist=shell_denylist or None,
    ))

    # Discover tools from tools/ directory
    register_discovered_tools(registry, tools_dir)

    return registry


def _default_memory_manager(
    db_path: str = "runtime.db",
    max_entries: int = 50,
    max_scratch_bytes: int = 256_000,
) -> MemoryManager:
    """Build memory-manager with SQLite-backed episodic and semantic tiers."""
    return MemoryManager(
        working=WorkingMemory(max_entries=max_entries, max_scratch_bytes=max_scratch_bytes),
        episodic=EpisodicMemory(db_path=db_path),
        semantic=SemanticMemory(db_path=db_path),
        procedural=ProceduralMemory(),
    )

def _default_llm_client(cfg: RuntimeConfig, logger: Optional[StructuredLogger] = None) -> LLMClient:
    """Create an LLM client using the configured registry."""
    return LLMClient(registry=cfg.llm_registry, logger=logger)


def _load_workflow_for_run(
    workflow_ref: str,
    handler_registry: StepHandlerRegistry,
    workflows_dir: str = "workflows",
) -> Dict[str, Any]:
    """Resolve workflow from file path or id/version registry reference."""
    if os.path.exists(workflow_ref):
        return load_workflow(workflow_ref, handler_registry)

    ref = parse_workflow_reference(workflow_ref)
    registry = WorkflowRegistry.from_directory(workflows_dir, handler_registry)
    return registry.get(ref.workflow_id, ref.version)


def _coerce_value(raw: str) -> Any:
    """Auto-coerce a CLI input string to its most likely Python type.

    Conversion order:
    1. ``true`` / ``false`` (case-insensitive) \u2192 bool
    2. Integer literal \u2192 int
    3. Float literal \u2192 float
    4. JSON array or object \u2192 parsed value
    5. Fallback \u2192 str (unchanged)
    """
    lower = raw.strip().lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    if raw.startswith(("{", "[")) and raw.endswith(("}", "]")):
        import json as _json
        try:
            return _json.loads(raw)
        except _json.JSONDecodeError:
            pass
    return raw


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
    """Parse ``-i key=value`` pairs and validate against the workflow input schema.

    Values are auto-coerced: ``true``/``false`` become booleans, numeric
    strings become int or float, and JSON-like values (arrays/objects) are
    parsed.  Plain strings are kept as-is.
    """
    provided: Dict[str, Any] = {}
    for item in raw_inputs:
        if "=" not in item:
            raise SystemExit(f"Invalid input format: {item!r}. Expected KEY=VALUE.")
        key, _, value = item.partition("=")
        key = key.strip()
        if not key:
            raise SystemExit(f"Invalid input: empty key in {item!r}")
        provided[key] = _coerce_value(value)

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
    """Execute CLI command dispatch and return process exit code."""
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

    visualize_parser = subparsers.add_parser("visualize", aliases=["viz"], help="Visualize run execution")
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
        logger = StructuredLogger(stream=sys.stderr)
        llm_client = _default_llm_client(cfg, logger)
        # Try agent-aware resolution: check agents/ for a manifest matching
        # the workflow arg as an agent_id (with optional @version).
        agent_manifest = _try_resolve_agent(args.workflow)

        try:
            if agent_manifest is not None:
                handler_registry = _default_handler_registry(cfg.handlers_dir, llm_client)
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
                handler_registry = _default_handler_registry(cfg.handlers_dir, llm_client)
                workflow = _load_workflow_for_run(args.workflow, handler_registry, cfg.workflows_dir)
                input_state = _build_input_state(args.input, workflow.get("inputs", {}))
        except FileNotFoundError:
            print(f"Error: workflow file not found: {args.workflow}", file=sys.stderr)
            return 1
        except yaml.YAMLError as exc:
            print(f"Error: invalid YAML in workflow file: {exc}", file=sys.stderr)
            return 1
        except WorkflowValidationError as exc:
            print(f"Error: workflow validation failed: {exc}", file=sys.stderr)
            return 1

        steps = workflow["steps"]

        storage = SQLiteStorage(cfg.db_path)
        memory_manager = _default_memory_manager(
            cfg.db_path,
            max_entries=cfg.working_memory_max_entries,
            max_scratch_bytes=cfg.working_memory_max_scratch_bytes,
        )
        tool_registry = _default_tool_registry(
            cfg.tools_dir,
            shell_allowlist=cfg.shell_allowlist or None,
            shell_denylist=cfg.shell_denylist or None,
        )

        def _progress_callback(event: str, payload: Dict[str, Any]) -> None:
            step_id = payload.get("step_id", "")
            step_type = payload.get("step_type", "")
            if event == "STEP_COMPLETE":
                duration = payload.get("duration_ms", "?")
                print(f"  \u2713 {step_id} ({step_type}) \u2014 {duration}ms")
            elif event == "STEP_ERROR":
                error = payload.get("error", "unknown error")
                print(f"  \u2717 {step_id} ({step_type}) \u2014 {error}")

        executor = Executor(
            steps=steps,
            storage=storage,
            logger=logger,
            memory_manager=memory_manager,
            tool_registry=tool_registry,
            overwrite_policy=cfg.overwrite_policy,
            on_event=_progress_callback,
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
        if run.status == "FAILED" and run.error:
            print(f"Error: {run.error}")
            print(f"\nRun `ai inspect {run.run_id}` to see full execution details.")
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
                    print(_redact(step.output))
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
            print(_redact(latest_state))

        if run.workflow_yaml:
            handler_registry = _default_handler_registry(cfg.handlers_dir, _default_llm_client(cfg))
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

        handler_registry = _default_handler_registry(cfg.handlers_dir, _default_llm_client(cfg))

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
            memory_manager=_default_memory_manager(
                cfg.db_path,
                max_entries=cfg.working_memory_max_entries,
                max_scratch_bytes=cfg.working_memory_max_scratch_bytes,
            ),
            tool_registry=_default_tool_registry(
                cfg.tools_dir,
                shell_allowlist=cfg.shell_allowlist or None,
                shell_denylist=cfg.shell_denylist or None,
            ),
            overwrite_policy=cfg.overwrite_policy,
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
                    print(f"+ {path} = {_redact(change['after'])}")
                elif op == "-":
                    print(f"- {path} (was {_redact(change['before'])})")
                else:
                    print(f"~ {path}: {_redact(change['before'])} -> {_redact(change['after'])}")
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
    """CLI entrypoint wrapper that exits with command status code."""
    raise SystemExit(run_cli())


if __name__ == "__main__":
    main()


def _diff_state(before: dict, after: dict) -> dict:
    """Return top-level state diff summary for CLI output."""
    # [TODO] Improve diff granularity beyond top-level keys.
    # [TODO] Add CLI graph visualization for branching workflows.
    return RuntimeState.diff(before, after)


def _print_state_history(steps, latest_state) -> None:
    """Print per-step state mutation summary for inspect command."""
    # [TODO] Support snapshot compression for large states.
    # [TODO] Handle large state output safely (pagination or truncation).
    if not steps:
        return
    initial = steps[0].state_before or latest_state
    print("\nState history:")
    print("Initial state:")
    print(_redact(initial))
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
            print(_redact(step.output))
        if step.state_after is not None:
            print("State after:")
            print(_redact(step.state_after))
        print("\n----------------------------------------")


def _render_timeline_text(run_id: str, timeline) -> str:
    """Render timeline view to plain text for `visualize --timeline`."""
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
