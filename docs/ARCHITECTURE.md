# Architecture

## Core Concepts
- Run: top-level execution record for a workflow.
- StepExecution: per-step execution record with input/output and timestamps.
- RunState: structured JSON state with `inputs` and `steps`.

## Execution Flow
1. Load workflow YAML into step definitions.
2. Create Run and initial state snapshot.
3. Execute steps sequentially with deterministic handler/tool output.
4. Persist step execution and state versions to SQLite.

## Retry and Failure Policy
- Steps can declare `retry.attempts` and `retry.delay_seconds`.
- Workflow can set `on_error: fail_fast` or `on_error: continue`.

## Storage
- SQLite backend with tables: `runs`, `steps`, `state_versions`.

## Memory Tiers
- Working
- Episodic
- Semantic
- Procedural

Each tier exposes `read` and `write` interfaces and is wired through `MemoryManager`.

## Tooling
- Tool registry provides named tool handlers.
- Tool discovery interface is defined for future dynamic discovery.
