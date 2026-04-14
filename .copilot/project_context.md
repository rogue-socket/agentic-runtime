# Project Context

## Project Overview
`agentic-runtime` is a deterministic local-first execution runtime for AI workflows. Workflows are YAML-defined, persisted to SQLite, resumable after failure, replayable without side effects, and observable through inspect/state-diff/visualization tooling.

The active authoring model is workflow-first with three primary step types:
- `agent` (LLM reasoning via agent definitions)
- `function` (deterministic Python transforms)
- `tool` (external actions)

## Tech Stack
- Language: Python 3.10+
- Local environment: conda env `agent_runtime`
- Persistence: SQLite (`runs`, `steps`, `state_versions`)
- Workflow format: YAML
- HTTP adapters: stdlib `urllib`
- CLI: `argparse` (`ai` entry point from `pyproject.toml`)
- Packaging: setuptools backend
- Core dependencies: `PyYAML`, `typing-extensions`
- Test stack: `pytest`, `pytest-asyncio`

## Architecture Snapshot
```
CLI (cli.py)
  -> Config (config.py)
  -> Registries (workflow/agent/tool/llm)
  -> Workflow parser (workflow.py)
  -> Executor (core.py)
      -> agent steps (agent/ + llm/)
      -> function steps (function_resolver.py + functions/)
      -> tool steps (tools/)
      -> memory hydration/persist (memory/)
      -> lifecycle events + timing telemetry
  -> Storage (storage/sqlite.py)
```

State contract remains:
```
{
  "inputs": {},
  "steps": {},
  "runtime": {}
}
```

## Key Directories
- `src/agent_runtime/core.py`: main executor loop, retries, branching, resume/replay hooks
- `src/agent_runtime/workflow.py`: parsing, validation, contracts, deprecated model-step compatibility
- `src/agent_runtime/cli.py`: command surface (`run`, `inspect`, `resume`, `replay`, `visualize`, etc.)
- `src/agent_runtime/agent/`: agent definitions, strategies, executor, registry, packaging
- `src/agent_runtime/llm/`: provider registry, adapters, client
- `src/agent_runtime/tools/`: tool protocol, registry, built-ins, discovery, validation
- `src/agent_runtime/memory/`: working/episodic/semantic/procedural tiers + manager
- `src/agent_runtime/storage/`: storage abstractions + SQLite implementation
- `src/agent_runtime/visualization/`: graph/timeline loaders and renderers
- `workflows/`: canonical workflow examples/samples
- `tests/`: broad runtime test coverage (README reports 448 passing)
- `planning/vision/todos.md`: categorized TODO index for planning

## Current Conventions
- Registry-based extensibility for tools, workflows, LLM providers, and agents.
- Namespaced state only; no ad hoc global dict mutation.
- Resume safety via workflow hashing.
- Branch expressions validated through `safe_eval` constraints.
- Structured logging and lifecycle callback events.
- Minimal dependency philosophy (no heavy HTTP SDK dependencies).

## TODO Taxonomy (Repo Standard)
Inline TODOs in source use:
- `TODO(roadmap): ...`
- `TODO(pain-point): ...`
- `TODO(ux): ...`
- `TODO(security): ...`
- `TODO(eng): ...`

Optional milestone tags (for explicit release gates):
- `TODO(0.2.0): ...`

Primary source for category inventory and current backlog: `planning/vision/todos.md`.

## Suggested Verification Commands
```bash
conda activate agent_runtime
pip install -r requirements.txt
pytest -q
```
