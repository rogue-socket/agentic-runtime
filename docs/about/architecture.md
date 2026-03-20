<!--
File: docs/about/architecture.md
Purpose: Defines the runtime's architectural model and execution contracts.
Description: Documents entities, control flow, state model, persistence, replay, and extension points.
Dependencies: Mirrors behavior implemented in src/agent_runtime.
Inputs/Outputs: Input for developers; output is shared architecture understanding.
Side Effects: None.
-->

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
- `agent` — delegates to an agent definition (LLM-backed reasoning)
- `function` — calls a plain Python function for deterministic logic
- `tool` — calls a tool class for external actions
- `model` — deprecated, kept for backward compatibility with existing tests

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

## Step types and dispatch

The Executor dispatches each step based on its `step_type`:

**Agent steps** (`type: agent`):
1. Resolve `AgentDefinition` from the `AgentRegistry` by agent id.
2. Instantiate `AgentExecutor` with the definition, `LLMClient`, and `ToolRegistry`.
3. Run the agent's pipeline using its configured strategy (single, react, or custom).
4. Capture `AgentResult` (outputs, trace, iterations, token usage).
5. Write outputs to `steps.<step_id>` in state; store trace in `StepExecution.agent_trace`.

**Function steps** (`type: function`):
1. Resolve function callable from `functions/` directory at parse time.
2. Build input dict from the step's `inputs` mapping.
3. Call `function_callable(inputs)` and capture the returned dict.
4. Write output to `steps.<step_id>` in state.

**Tool steps** (`type: tool`):
1. Resolve tool from `ToolRegistry` by name.
2. Validate input against `input_schema`.
3. Call `tool.execute(input, context)` with runtime context.
4. Write output to `steps.<step_id>` in state.

**Model steps** (`type: model`, deprecated):
Kept for backward compatibility with existing tests. Calls a handler function
(`Callable[[RuntimeState], dict]`) resolved during workflow parsing.

### Agent definitions

Agent YAML files live in `agents/` and describe LLM-backed reasoning units:

```yaml
agent:
  id: code_reviewer
  version: v1
  model: gemini/gemini-2.5-flash
  system: "You are a senior code reviewer."
  strategy:
    type: react
    max_iterations: 5
  tools:
    - tools.file
  pipeline:
    - id: analyze
      type: model
      prompt: "Analyze this code: {{ inputs.diff }}"
    - id: review
      type: model
      prompt: "Write review based on: {{ analyze.text }}"
```

Key classes (module `agent/`):
- `AgentDefinition` — parsed agent dataclass with pipeline, strategy, tools
- `AgentRegistry` — discovers and resolves agents from `agents/` directory
- `AgentExecutor` — runs the agent pipeline with the configured strategy
- `StrategyConfig` — strategy type and parameters
- `PipelineStep` — individual step within an agent's pipeline

Strategies:
- `SingleCallStrategy` — run pipeline once linearly
- `ReActStrategy` — observe→think→act loop with max iterations
- Custom strategies via dotted import path (`strategy.handler`)

### Function resolution

Functions live in `functions/` and are referenced by qualified name:
- `stubs.generate_summary` → `functions/stubs.py` → `generate_summary()`
- `formatters.format_markdown` → `functions/formatters.py` → `format_markdown()`

Resolution happens at parse time (fail fast). Module: `function_resolver.py`.

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

Built-in tools (`tools.echo`, `tools.http`, `tools.file`, `tools.shell`) are always available regardless of what's in `tools/`.

### Built-in tools

| Tool | Name | Description |
|------|------|-------------|
| `EchoTool` | `tools.echo` | Returns input message (testing/examples) |
| `HttpTool` | `tools.http` | HTTP/HTTPS requests with scheme validation |
| `FileTool` | `tools.file` | Read/write/append/list files (sandboxed to root) |
| `ShellTool` | `tools.shell` | Execute shell commands with timeout + output capture |

Modules:
- `tools/base.py` — `Tool` protocol, `ToolResult`, `RuntimeContext`
- `tools/registry.py` — `ToolRegistry`
- `tools/discovery.py` — `ToolDiscovery`, `discover_tools()`, `register_discovered_tools()`
- `tools/echo.py` — built-in `EchoTool`
- `tools/http.py` — built-in `HttpTool`
- `tools/file.py` — built-in `FileTool`
- `tools/shell.py` — built-in `ShellTool`
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

The runtime manages four memory tiers through `MemoryManager`:

| Tier | Class | Status | Purpose |
|------|-------|--------|--------|
| Working | `WorkingMemory` | **Implemented** | Active context for current execution (scratch store, sliding window, active task) |
| Episodic | `EpisodicMemory` | **Implemented** | Historical run/interaction log (SQLite-backed) |
| Semantic | `SemanticMemory` | **Implemented** | Long-term knowledge store (SQLite + FTS5 full-text search) |
| Procedural | `ProceduralMemory` | Stub | Learned workflows and playbooks (roadmap documented) |

All tiers implement the `MemoryTier` protocol:
- `read(context) -> Dict[str, Any]`
- `write(payload) -> None`

`MemoryManager` orchestrates all tiers:
- `hydrate_state(state)` — reads from all tiers into `runtime.memory.<tier>` namespace using deep-merge
- `persist_state(state)` — writes state to all tiers after execution
- `_tiers()` — yields `(name, tier)` pairs for iteration
- `_deep_merge()` — recursive dict merge utility

Memory hooks are invoked at run start (hydrate) and run end (persist).

### Working memory

`WorkingMemory` is an in-memory ephemeral store for the current execution:
- **Scratch** — key-value store with byte budget enforcement (`put/get/remove/clear_scratch`)
- **Entries** — deque-based sliding window with `max_entries`, auto-eviction
- **Active task** — single current objective dict
- `write()` auto-captures latest step output as a context entry
- `reset()` clears all state at run end
- Configurable limits: `working_memory_max_entries`, `working_memory_max_scratch_bytes` in `RuntimeConfig`

### Episodic memory (SQLite)

`EpisodicMemory` stores condensed episode records per run.  It tracks:
- `workflow_id`, `run_id`, `status`
- `inputs_summary` (key names), `outputs_summary` (step names)
- `error` (if failed), `created_at`

Query API:
- `record(...)` — write a single episode row
- `recall(workflow_id, limit)` — most recent episodes for a workflow
- `recall_all(limit)` — most recent across all workflows

`read()` hydrates `runtime.memory.episodic` with past episodes for the current workflow,
giving handlers context about prior runs.

When no `db_path` is provided, `EpisodicMemory` operates as an in-memory stub
(backward compatible with tests and default CLI).

### Semantic memory (SQLite + FTS5)

`SemanticMemory` stores long-term knowledge facts with full-text search:
- `store(key, content, tags, metadata)` — insert/update with FTS5 index sync
- `get(key)` — exact key lookup
- `delete(key)` — removes fact + FTS index entry
- `search(query, limit)` — FTS5 MATCH with BM25 ranking, prefix tokenization (`tokenize='porter unicode61'`)
- `search_by_tags(tags, match_all)` — tag-based query with match_all/match_any modes
- `count()` — total fact count

Protocol-driven: `read()` looks for `runtime.memory.semantic.query` in state; `write()` persists facts from `runtime.memory.semantic.store` list.

Falls back to in-memory dict when no `db_path` is provided.

**Not yet implemented:** vector-similarity retrieval (embeddings + cosine distance) — roadmap item.

### Procedural memory (stub)

`ProceduralMemory` is currently a stub. Roadmap: mine episodic history for patterns, store rules in SQLite, confidence scoring, LLM-assisted extraction.

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
- `tools_dir` — tool discovery directory (default: `tools`)
- `agents_dir` — agent definition directory (default: `agents`)
- `functions_dir` — function discovery directory (default: `functions`)
- `logging.level` / `logging.format` — log configuration
- `overwrite_policy` — state overwrite behavior: `warn` (default), `strict`, `allow`
- `working_memory_max_entries` — max sliding window entries (default: 50)
- `working_memory_max_scratch_bytes` — max scratch store size (default: 256KB)
- `shell_allowlist` / `shell_denylist` — regex patterns for ShellTool command filtering
- `default_llm_provider` — fallback provider for ambiguous model references
- `llm:` — provider configuration block (providers, models, API key env vars)

Module: `config.py` — `RuntimeConfig`, `load_config()`, `apply_cli_overrides()`

## 17. Lifecycle hooks

The Executor emits structured events at five lifecycle points via an optional `EventCallback`:

```python
EventCallback = Callable[[str, Dict[str, Any]], None]
```

Events:
| Event | When | Payload includes |
|-------|------|------------------|
| `RUN_START` | Run begins | `run_id`, `workflow_id` |
| `STEP_START` | Step begins | `run_id`, `step_id`, `step_type` |
| `STEP_COMPLETE` | Step succeeds | `run_id`, `step_id`, `duration_ms`, `handler_duration_ms`/`tool_duration_ms` |
| `STEP_ERROR` | Step fails (after retries) | `run_id`, `step_id`, `error` |
| `RUN_COMPLETE` | Run finishes | `run_id`, `status`, `total_duration_ms` |

Usage: pass `on_event` to `Executor.__init__()` or to `run_workflow()`.

## 18. Timing telemetry

Per-step timing captures both total step duration and call-specific latency:
- `duration_ms` — total time from state_before snapshot to state_after persistence
- `handler_duration_ms` — time spent inside the handler callable (model steps)
- `tool_duration_ms` — time spent inside the tool's `execute()` method (tool steps)

Run-level duration is derived from `started_at` / `completed_at` timestamps.

Visualization renderers (HTML, ASCII) and CLI progress output surface these metrics.

## 19. Extension points

Designed for future expansion:
- Stronger expression engine for branching (`.startswith()`, `in`, min/max)
- DAG scheduler and parallel step execution
- Typed state schemas
- Tool permissions and sandbox policies
- State redaction and compression for large payloads
- LLM streaming / token-level events
- Native LLM function calling (vs text-based tool_call parsing)
- Multi-agent composition (sub-workflow invocation)
- PostgreSQL storage backend
- Remote storage (S3 + DynamoDB)
- OpenTelemetry / Prometheus observability
- Vector/embedding search for semantic memory
- Procedural memory pattern extraction

## 20. LLM registry

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
and is available for agents and the LLM client to determine which model to use.

### LLM call pipeline

`LLMClient` routes requests through provider-specific adapters:

```
workflow YAML (handler: llm, model, prompt)
  → make_llm_handler() → LLMClient.call()
    → resolve provider/model
    → adapter.call() (HTTP to provider API)
    → LLMResponse (text, usage, raw)
```

Adapters:
- `OpenAIAdapter` — Chat Completions API (`/v1/chat/completions`)
- `AnthropicAdapter` — Messages API (`/v1/messages`)
- `GeminiAdapter` — Gemini generateContent API

All adapters use stdlib `urllib` (zero additional dependencies) with exponential-backoff retry on 429/5xx errors.

Built-in `llm` handler:
- Registered as `handler: llm` in workflow YAML
- Reads `model`, `prompt`, `system`, `provider`, `temperature`, `max_tokens` from step definition
- Supports `{{ path }}` template syntax in prompts
- Returns response text under configurable key (default: `text`)
- Optional `include_metadata: true` captures provider, model, and token usage in output

> **Status: Implemented** — registry, config loading, credential resolution,
> OpenAI adapter, Anthropic adapter, Gemini adapter, LLM client, and built-in handler are
> functional.  All adapters are synchronous (stdlib `urllib`) with exponential-backoff
> retry on 429/5xx errors.  Streaming is a future enhancement.

## 20.5. Agent system

The runtime has two agent subsystems:

### Agent definitions (current)

Agent definitions (`agents/*.yaml`) describe LLM-backed reasoning units with
model, strategy, pipeline, tools, and prompt configuration. They are referenced
from workflow steps via `type: agent`.

Key classes (module `agent/`):
- `AgentDefinition` — parsed definition dataclass
- `AgentRegistry` — discovers and resolves agents from directory
- `AgentExecutor` — runs agent pipeline with configured strategy
- `PromptRegistry` — manages versioned prompts for A/B testing

### Agent manifests (legacy)

Agent manifests (`agent.yaml`) are the legacy portable unit that declares
a workflow plus its handlers, tools, providers, and environment variables.
Still supported for `ai validate`, `ai export`, and `ai import` commands.

Key classes (module `agent/`):
- `AgentManifest` — parsed manifest dataclass
- `ValidationResult` — pre-flight check result

### Manifest schema (legacy)

```yaml
agent:
  id: triage_agent
  version: v2
  description: "Triages incoming issues by severity"
  runtime: ">=0.1"

workflow: workflows/triage.yaml

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

## 21. Status summary

| Capability | Status |
|---|---|
| Core execution engine | Implemented |
| Retry / backoff (fixed + exponential) | Implemented |
| Conditional branching + circular detection | Implemented |
| SQLite persistence (WAL, transactions) | Implemented |
| Resume from failure | Implemented |
| Workflow hash lock on resume | Implemented |
| Deterministic replay | Implemented |
| State diff & visualization (HTML + ASCII) | Implemented |
| Workflow versioning & registry | Implemented |
| Step contracts (input + output) | Implemented |
| Tool subsystem & auto-discovery | Implemented |
| Function resolution (fail-fast) | Implemented |
| LLM provider registry | Implemented |
| Credential resolution (env vars only) | Implemented |
| Agent definition system (pipeline + strategy) | Implemented |
| Agent manifest system (legacy) | Implemented |
| Agent validate / export / import | Implemented |
| Agent-aware run resolution | Implemented |
| Prompt versioning (`id@vN`) | Implemented |
| Function step type | Implemented |
| Agent step type | Implemented |
| Tool step type | Implemented |
| LLM adapters (OpenAI, Anthropic, Gemini) | Implemented |
| Adapter retry with backoff (429/5xx) | Implemented |
| Async executor with sync wrappers | Implemented |
| Built-in tools (Echo, HTTP, File, Shell) | Implemented |
| Working memory (scratch + sliding window) | Implemented |
| Episodic memory (SQLite) | Implemented |
| Semantic memory (SQLite + FTS5) | Implemented |
| Procedural memory | Stub |
| Lifecycle hooks (event callbacks) | Implemented |
| Timing telemetry (per-step + run-level) | Implemented |
| `safe_eval` sandboxed expressions | Implemented |
| Multi-workflow agents | Planned |
| DAG / parallel execution | Planned |
| LLM streaming | Planned |
| Vector/embedding search | Planned |
| PostgreSQL storage backend | Planned |
| OpenTelemetry / metrics | Planned |
| Tool permissions / sandboxing | Planned |
| Idempotency keys | Planned |
