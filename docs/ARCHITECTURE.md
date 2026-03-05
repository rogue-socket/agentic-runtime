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

## 7. Persistence model (SQLite)

Tables:
- `runs`
- `steps`
- `state_versions`

Properties:
- run metadata is durable
- step timeline is ordered (`execution_index`)
- full state evolution is queryable (`state_versions` + `state_before/state_after`)

## 8. Resume semantics

`ai resume <run_id>`:

1. Validate run is resumable (`FAILED` only).
2. Validate workflow hash compatibility.
3. Determine resume step from recorded history.
4. Load latest state snapshot.
5. Continue execution from resume step.

Determinism principle:
- completed history is preserved
- resumed traversal uses same branch/step resolution logic

## 9. Replay semantics

`ai replay <run_id>` is simulation, not execution.

Replay engine:
- loads run + step history + initial state
- replays step timeline by injecting recorded state transitions
- does not call handlers/tools/models
- optional `--verify-state` checks reconstructed state against `state_before`

Use this for postmortems and reproducibility checks.

## 10. Observability surfaces

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

## 11. Determinism guardrails (current)

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

## 12. Extension points

Designed for future expansion:
- stronger expression engine for branching
- DAG scheduler and parallel step execution
- typed state schemas
- tool permissions and sandbox policies
- state redaction and compression for large payloads
