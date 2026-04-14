# Project Context

Last refreshed: 2026-04-14

## Project Overview
`agentic-runtime` is a workflow-first execution runtime for deterministic AI pipelines with:
- durable SQLite-backed run/state persistence
- resume after failure
- deterministic replay
- branch-aware state transitions
- CLI-first observability (`inspect`, `state-diff`, `visualize`)

Primary workflow step model:
- `type: agent` for LLM-backed reasoning from `agents/*.yaml`
- `type: function` for deterministic Python callables in `functions/*.py`
- `type: tool` for tool protocol implementations in `tools/*.py`

## Repository Layout
- Runtime framework code: `src/agent_runtime/`
- Docs and product narrative: `documentation/`
- Planning and backlog: `planning/`
- Example runnable project: `examples/reference_project/`
- Additional sample projects: `agent-test-one/`, `essay_writer/`
- Test suite: `tests/`

## Architecture Snapshot
```
CLI (src/agent_runtime/cli.py)
  -> Config + runtime bootstrap
  -> Registries (workflow/agent/tool/llm)
  -> Workflow parser/validator (workflow.py)
  -> Executor (core.py)
      -> agent execution (agent/ + llm/)
      -> function dispatch (function_resolver.py)
      -> tool dispatch (tools/)
      -> memory hydration/persist (memory/)
      -> lifecycle events + telemetry
  -> Storage abstractions (storage/) backed by sqlite.py
```

State contract:
```
{
  "inputs": {},
  "steps": {},
  "runtime": {}
}
```

## Key Modules
- `src/agent_runtime/core.py`: executor loop, retries, branching, resume hooks
- `src/agent_runtime/workflow.py`: workflow schema parsing and contracts
- `src/agent_runtime/cli.py`: user-facing command surface
- `src/agent_runtime/agent/`: agent definitions, strategy runtime, execution
- `src/agent_runtime/llm/`: provider adapters + request controls
- `src/agent_runtime/tools/`: built-ins, discovery, validation, protocol
- `src/agent_runtime/memory/`: working/episodic/semantic/procedural tiers
- `src/agent_runtime/storage/`: base interface and SQLite persistence
- `src/agent_runtime/visualization/`: timeline/graph rendering

## Source-of-Truth Docs
- `documentation/about/architecture.md`
- `documentation/about/status_2026-03-17.md`
- `documentation/about/gaps_2026-03-17.md`
- `documentation/changelog/CHANGELOG_2026-03-31.md`
- `planning/vision/todos.md`

## Current Engineering Conventions
- Registry-based extensibility for agents, tools, workflows, and LLM providers.
- Namespaced runtime state with explicit step output ownership.
- Resume safety based on workflow hashing.
- Branch conditions must stay within `safe_eval` constraints.
- Structured logging over ad hoc prints.
- Minimal dependency philosophy (stdlib HTTP via `urllib`).

## TODO Taxonomy
Use categorized TODOs:
- `TODO(roadmap): ...`
- `TODO(pain-point): ...`
- `TODO(ux): ...`
- `TODO(security): ...`
- `TODO(eng): ...`

Allowed for release-gated work:
- `TODO(<milestone>): ...` (example: `TODO(0.2.0): ...`)

## Environment Guidance
- Preferred local environment for this workspace: conda env `wa-data` (if present)
- Project docs often reference: conda env `agent_runtime`
