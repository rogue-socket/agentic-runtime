# Architecture

This document describes the runtime as an execution system: data model, control flow, persistence, determinism guarantees, and extension points.

## 1. Runtime model

`agentic-runtime` executes workflow definitions into durable run records.

Execution contract:

1. Load workflow definition.
2. Create run record and initial state snapshot.
3. Execute step-by-step with retry/branch logic.
4. Persist step records and state versions after each step.
5. Mark run terminal (`COMPLETED`, `FAILED`, or `COMPLETED_WITH_ERRORS`).

The runtime is local-first with SQLite persistence.

## 2. Core entities

## `Run`
Top-level execution record.

Key fields:
- `run_id`
- `workflow_id`
- `workflow_version`
- `workflow_hash`
- `workflow_yaml`
- `workflow_steps`
- `input_hash`
- `status`
- `created_at`, `started_at`, `completed_at`
- `error`

## `StepExecution`
One executed step instance in timeline order.

Key fields:
- `step_id`, `step_type`
- `execution_index`
- `status`
- `attempt_count`
- `input`, `output`
- `error`, `last_error`
- `state_before`, `state_after`
- `started_at`, `finished_at`, `duration_ms`

## `RuntimeState`
State manager abstraction used during execution (instead of ad-hoc raw dict mutation).

APIs:
- `get(key)`
- `set(key, value, step_name=None)`
- `exists(key)`
- `delete(key)`
- `snapshot()`
- `to_dict()`
- `set_step_output(step_name, output)`
- `diff(before, after)`

## 3. State contract

Runtime state shape is namespaced:

```json
{
  "inputs": {},
  "steps": {},
  "runtime": {}
}
```

Rules:
- `inputs`: request/context input payload for the run.
- `steps.<step_id>`: owned output namespace per step.
- `runtime`: runtime-level metadata namespace.

Why this matters:
- prevents cross-step key collisions
- preserves step output ownership
- makes branch and replay analysis tractable

## 4. Workflow model

Workflows are YAML with identity metadata and ordered `steps`.

Workflow metadata:
- `workflow.id`
- `workflow.version`

Workflow-level input declarations:
- `inputs:` declares what the workflow expects from the caller
- Supports mapping form (with `description`, `required`, `default`) or list shorthand
- `inputs_contract` (legacy list form) is still supported for backward compatibility
- Workflows without input declarations infer available inputs from step references

Step types:
- `model`
- `tool`

Step controls:
- `inputs` mapping from state paths (`inputs.issue`, `steps.a.summary`)
- `inputs` contract list (`[issue, summary]`) for declared read dependencies
- `outputs` contract list (`[summary, sentiment]`) for declared write boundaries
- `retry` policy (`attempts`, `backoff`, `initial_delay`)
- `next` branching rules (`when`/`goto`, optional `default`)

Workflow-level control:
- `on_error: fail_fast | continue`

Versioning behavior:
- `ai run <workflow_id>` resolves latest `vN` from registry scan in `workflows/`
- `ai run <workflow_id>@<version>` resolves exact version
- `ai run <path/to/workflow.yaml>` remains supported
- run record stores workflow snapshot (`workflow_yaml`) for replay stability even if files change later

## 5. Execution engine (`Executor`)

## Handlers (model step functions)

A handler is a Python function that implements the logic for a `model` step.

The contract:
```python
StepHandler = Callable[[RuntimeState], Dict[str, Any]]
```

A handler receives the step's input as a `RuntimeState` and returns a dict of outputs. The runtime manages everything else — retries, state snapshots, persistence, resume.

Lifecycle:
1. Workflow YAML declares `handler: <name>` on a `model` step.
2. At startup, built-in handlers are registered and the `handlers/` directory is scanned for user-defined handlers.
3. During workflow loading, the name is resolved to the actual function and attached to the `StepDefinition`.
4. At execution time, `Executor` calls `step_def.handler(step_input_state)` and captures the returned dict.
5. The output dict is written to `steps.<step_id>` in state.

Registration (built-in):
```python
registry = StepHandlerRegistry()
registry.register("generate_summary", generate_summary)
```

Auto-discovery from `handlers/` directory:
```python
from agent_runtime.handler_discovery import register_discovered_handlers
register_discovered_handlers(registry, "handlers")
```

Discovery conventions (per module in `handlers/`):
1. **Zero-config:** every public function (name not starting with `_`) is registered using the function name.
2. **Explicit:** define a `__handlers__` dict mapping handler names to functions. This gives full naming control and skips helper functions.

Example handler:
```python
def generate_summary(state: RuntimeState) -> Dict[str, Any]:
    issue = state["issue"]
    return {"summary": f"Summary of: {issue}"}
```

Handlers are distinct from tools:
- **Handlers** are plain functions (`Callable[[RuntimeState], dict]`) for `model` steps.
- **Tools** implement the `Tool` protocol (with `execute`, `input_schema`, etc.) for `tool` steps.

Modules:
- `steps.py` — `StepHandlerRegistry` and built-in handlers
- `handler_discovery.py` — directory-based handler auto-discovery

## Step pointer model
Executor uses a pointer (`current_step_id`) rather than list-only traversal.

Benefits:
- linear flow support
- conditional branching support
- consistent resume semantics

## Step execution algorithm
For each step:

1. Capture `state_before` snapshot.
2. Build step input from `inputs` mapping (or snapshot fallback).
3. Execute with retry policy.
4. Validate output structure.
5. Write output to `steps.<step_id>` namespace.
6. Capture `state_after` snapshot.
7. Persist `StepExecution` + new state version.
8. Resolve next step via branch rules or sequential fallback.

## Step contracts
Step contracts make state boundaries explicit:

- reads = `inputs`
- writes = `outputs`

Validation at workflow load:
- future-read detection for contract inputs
- output collision detection

Validation at runtime:
- output contract enforcement (missing or undeclared keys fail step)

This keeps step interfaces stable as workflows grow.

## Branch resolution
`next` rules are evaluated top-to-bottom:
- first `when` evaluating `True` wins
- else `default` if present
- else branch resolution failure

Expression context is constrained (`state`, `len`) to keep evaluation deterministic and safer.

## 6. Tool subsystem

Tools are first-class runtime components.

Interfaces:
- `Tool`
- `ToolResult`
- `RuntimeContext`

`ToolRegistry` stores tool objects, not plain functions.

Tool execution path includes:
- schema validation (`input_schema`)
- runtime context injection (`run_id`, `step_id`, state, logger)
- optional per-tool timeout/retries
- structured tool events:
  - `TOOL_START`
  - `TOOL_SUCCESS`
  - `TOOL_ERROR`

### Tool auto-discovery

The runtime automatically discovers tools from the `tools/` directory.

Discovery convention: every class in a module that satisfies the Tool protocol
(has `name`, `description`, `input_schema`, and `execute`) and whose class name
does not start with `_` is instantiated and registered.

Classes imported from other modules (e.g. base classes) are skipped via `__module__` check.

Built-in tools (`tools.echo`) are always available regardless of what's in `tools/`.

Modules:
- `tools/base.py` — `Tool` protocol, `ToolResult`, `RuntimeContext`
- `tools/registry.py` — `ToolRegistry`
- `tools/discovery.py` — `ToolDiscovery`, `discover_tools()`, `register_discovered_tools()`
- `tools/echo.py` — built-in `EchoTool`
- `tools/validation.py` — input schema validation

## 7. Persistence model (SQLite)

Tables:
- `runs`
- `steps`
- `state_versions`

Properties:
- run metadata is durable
- step timeline is ordered (`execution_index`)
- full state evolution is queryable (`state_versions` + `state_before/state_after`)

## 8. Memory subsystem

> **Status: Scaffolding** — interfaces are defined and wired into the execution
> loop, but all four tiers are stub implementations.  No persistence, vector
> search, or retrieval logic exists yet.

The runtime manages four memory tiers through `MemoryManager`:

| Tier | Class | Purpose |
|------|-------|---------|
| Working | `WorkingMemory` | Active context for current execution |
| Episodic | `EpisodicMemory` | Historical run/interaction log |
| Semantic | `SemanticMemory` | Long-term knowledge store |
| Procedural | `ProceduralMemory` | Learned workflows and playbooks |

All tiers implement the `MemoryTier` protocol:
- `read(context) -> Dict[str, Any]`
- `write(payload) -> None`

`MemoryManager` orchestrates all tiers:
- `hydrate_state(state)` — reads from all tiers into state before execution
- `persist_state(state)` — writes state to all tiers after execution

Memory hooks are invoked at run start (hydrate) and run end (persist).

Modules:
- `memory/base.py` — `MemoryTier` protocol and `MemoryManager`
- `memory/working.py` — `WorkingMemory`
- `memory/episodic.py` — `EpisodicMemory`
- `memory/semantic.py` — `SemanticMemory`
- `memory/procedural.py` — `ProceduralMemory`

## 9. Workflow registry and version resolution

`WorkflowRegistry` resolves workflow references to loaded workflow definitions.

Resolution rules:
- `ai run <workflow_id>` — scans `workflows/**/*.yaml` and `*.yml`, selects highest `vN` for matching `workflow.id`
- `ai run <workflow_id>@<version>` — resolves exact version
- `ai run <path>` — direct file load (no registry scan)

Key classes:
- `WorkflowRegistry` — scans directories, registers workflows, resolves by id/version
- `WorkflowReference` — frozen dataclass with `workflow_id` and `version`
- `parse_workflow_reference(value)` — parses `"id"` or `"id@version"` strings

Module: `workflow_registry.py`

## 10. Error hierarchy

All runtime exceptions inherit from `RuntimeErrorBase(Exception)`:

- `WorkflowValidationError` — invalid workflow YAML (bad step ids, missing targets, invalid retry)
- `StepExecutionError` — step handler or tool failure during execution
- `ToolNotFoundError` — tool name not registered in `ToolRegistry`
- `HandlerNotFoundError` — handler name not registered in `StepHandlerRegistry`
- `BranchResolutionError` — no matching `when` rule and no `default`
- `RunNotFoundError` — run id not found in storage
- `ReplayDataMissingError` — incomplete step/state data for replay
- `ReplayMismatchError` — reconstructed state diverges from recorded state during `--verify-state`
- `WorkflowIntegrityError` — workflow YAML has been modified since the original run (blocks resume)

Module: `errors.py`

## 11. Logging and utilities

### Structured logger

`StructuredLogger` emits JSON events to stderr:
- `info(event, payload)` — informational events
- `error(event, payload)` — error events
- `from_dataclass(event, obj)` — serializes dataclass objects into log entries

Module: `logging.py`

### Utilities

Key functions in `utils.py`:
- `utc_now()` — timezone-aware UTC timestamp
- `sha256_text(text)` / `sha256_json(data)` — deterministic hashing for workflow and input fingerprinting
- `resolve_path(path, state)` — resolves dot-notation paths like `steps.generate_summary.summary`
- `build_step_input(input_spec, state)` — materializes step input from state path mapping
- `safe_eval(expr, state)` — constrained expression evaluation for branch conditions (AST-validated, allows only `state` and `len`)
- `format_template(value, state)` — recursive template resolution in input specs

## 12. Resume semantics

`ai resume <run_id>`:

1. Validate run is resumable (`FAILED` only).
2. **Validate workflow hash** — the runtime compares the stored workflow hash
   against the current workflow hash and raises `WorkflowIntegrityError` if they
   differ.  This prevents resuming a run whose workflow definition has been
   modified since the original execution.
3. Determine resume step from recorded history.
4. Load latest state snapshot.
5. Continue execution from resume step.

Determinism principle:
- completed history is preserved
- resumed traversal uses same branch/step resolution logic

## 13. Replay semantics

`ai replay <run_id>` is simulation, not execution.

Replay engine:
- loads run + step history + initial state
- replays step timeline by injecting recorded state transitions
- does not call handlers/tools/models
- optional `--verify-state` checks reconstructed state against `state_before`

Use this for postmortems and reproducibility checks.

## 14. Observability surfaces

CLI modes:
- `inspect` summary
- `inspect --steps` step-centric details
- `inspect --state-history` state timeline and diff markers
- `state-diff` deep key-path state changes
- `visualize` run visualization:
  - `--ascii`
  - `--timeline`
  - default HTML (`.runs/<run_id>/visualization.html`)

Diff markers:
- `+` added
- `-` removed
- `~` changed

Visualization internals:
- `visualization/run_loader.py`: loads run, steps, state, workflow metadata
- `visualization/graph_builder.py`: execution nodes/edges + branch decision reconstruction
- `visualization/timeline_builder.py`: state deltas + step timing/tool detail timeline
- `visualization/ascii_renderer.py`: terminal-friendly view
- `visualization/html_renderer.py`: local standalone HTML report

## 15. Determinism guardrails (current)

Implemented:
- workflow id/version/hash snapshot on every run
- workflow hash + input hash capture
- step output namespacing
- persisted execution ordering
- state snapshots for before/after
- replay from persisted history

Known limitations:
- no full event-sourcing ledger
- no idempotency keys for side-effect tools
- no loop scheduler/loop detector beyond current guards

## 16. Runtime configuration

The runtime loads settings from `runtime.yaml` (if present), falling back to built-in defaults.

Precedence (highest wins):
```
CLI flag  >  runtime.yaml  >  built-in default
```

Config fields:
- `db_path` — SQLite database path (default: `runtime.db`)
- `workflows_dir` — workflow YAML directory (default: `workflows`)
- `handlers_dir` — handler discovery directory (default: `handlers`)
- `tools_dir` — tool discovery directory (default: `tools`)
- `model` — model backend settings (placeholder for LLM integration)
- `logging.level` / `logging.format` — log configuration

Module: `config.py` — `RuntimeConfig`, `load_config()`, `apply_cli_overrides()`

## 17. Extension points

Designed for future expansion:
- stronger expression engine for branching
- DAG scheduler and parallel step execution
- typed state schemas
- tool permissions and sandbox policies
- state redaction and compression for large payloads

## 18. LLM registry

The runtime includes a provider registry for managing LLM backends.

Key classes (module `llm/`):
- `LLMProvider` — one provider (name, API key env var, base URL, model configs)
- `ModelConfig` — one model definition (model_id, temperature, max_tokens, extras)
- `LLMRegistry` — central lookup of providers and models

Credential management:
- API keys are resolved from environment variables at call time — never stored on disk.
- `provider.resolve_api_key()` reads `os.environ[api_key_env]`.
- `registry.check_credentials()` returns a quick health map.

Configuration (in `runtime.yaml`):
```yaml
llm:
  providers:
    openai:
      api_key_env: OPENAI_API_KEY
      models:
        gpt-4:
          temperature: 0.2
          max_tokens: 4096
    anthropic:
      api_key_env: ANTHROPIC_API_KEY
      models:
        claude-3-opus:
          temperature: 0.3
    local:
      api_key_env: LOCAL_LLM_KEY
      base_url: http://localhost:8080/v1
      models:
        llama-3:
          temperature: 0.5
          max_tokens: 2048
```

The registry is loaded from the `llm` section of `RuntimeConfig` during startup
and is available for handlers to query which model to use.

> **Status: Implemented** — registry, config loading, and credential resolution
> are functional.  Actual LLM API call adapters (HTTP clients for
> OpenAI/Anthropic/local) are not yet implemented — model-type step handlers
> currently return deterministic stub output.

## 19. Agent manifest system

An agent manifest (`agent.yaml`) is the portable unit of the runtime.  It
declares everything an agent needs to run — workflow, handlers, tools, LLM
providers, and environment variables — in a single file.

Manifests live in the `agents/` directory.  Multiple agents can coexist
in one project, sharing handlers and tools.

Key classes (module `agent/`):
- `AgentManifest` — parsed manifest dataclass
- `ProviderRequirement` — LLM provider + models the agent depends on
- `ValidationResult` — one pre-flight check result

### Manifest schema

```yaml
agent:
  id: triage_agent
  version: v2
  description: "Triages incoming issues by severity"
  runtime: ">=0.1"

workflow: workflows/triage.yaml

handlers:
  - handlers/classify.py
  - handlers/summarize.py

tools:
  - tools/github_tool.py

providers:
  - name: openai
    models: [gpt-4, gpt-4o-mini]

env:
  - GITHUB_TOKEN

defaults:
  issue: "unspecified"
```

### CLI commands

- `ai validate <manifest>` — pre-flight checks (files, providers, env vars)
- `ai export <manifest> [-o output.tar.gz]` — bundle into portable archive
- `ai import <archive> [--path .]` — extract into project, place manifest in `agents/`
- `ai list` — list all agents in `agents/`
- `ai run <agent_id>[@version]` — resolves from `agents/`, merges defaults with `-i` overrides

### Agent-aware run resolution

When `ai run <ref>` is invoked, the runtime first checks `agents/` for a
matching `agent.id`.  If found, the manifest's workflow path is used and
default inputs are merged (CLI `-i` overrides take precedence).  If no
agent matches, the runtime falls back to workflow resolution (file path or
workflow registry).

### Export / Import flow

**Export** bundles `agent.yaml` + workflow + handlers + tools into a
self-contained `.tar.gz` archive.  The archive does not include
`runtime.yaml` (machine-specific) or the runtime itself.

**Import** extracts the archive into the project tree and places the
manifest in `agents/`.  Post-import validation reports missing providers
and env vars so the operator can configure the environment.

> **Status: Implemented** — manifest loading, validation, export, import,
> CLI commands, and agent-aware run resolution are functional.
> TODO: Support multiple workflows per agent with a designated entry point.

## 20. Status summary

| Capability | Status |
|---|---|
| Core execution engine | Implemented |
| Retry / backoff | Implemented |
| Conditional branching | Implemented |
| SQLite persistence | Implemented |
| Resume from failure | Implemented |
| Workflow hash lock on resume | Implemented |
| Deterministic replay | Implemented |
| State diff & visualization | Implemented |
| Workflow versioning & registry | Implemented |
| Step contracts | Implemented |
| Tool subsystem & discovery | Implemented |
| Handler auto-discovery | Implemented |
| LLM provider registry | Implemented |
| Credential resolution (env vars) | Implemented |
| Agent manifest system | Implemented |
| Agent validate / export / import | Implemented |
| Agent-aware run resolution | Implemented |
| LLM API call adapters | Planned |
| Memory tiers (4-tier) | Scaffolding |
| Multi-workflow agents | Planned |
| DAG / parallel execution | Planned |
| Tool permissions / sandboxing | Planned |
| Idempotency keys | Planned |
| Event sourcing ledger | Planned |
