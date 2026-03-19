**About The Codebase**

This folder explains how the runtime is structured and how it behaves under the hood.

- [Architecture](architecture.md) — the execution model, data model, and extension points
- [Status 2026-03-17](status_2026-03-17.md) — implementation status snapshot
- [Gaps 2026-03-17](gaps_2026-03-17.md) — known gaps and planned work
- [Git Runtime Date](git_runtime_date.md) — source control date reference

**Where The Code Lives**

- `src/agent_runtime/cli.py` — CLI entrypoints and orchestration
- `src/agent_runtime/core.py` — executor and step execution logic
- `src/agent_runtime/workflow.py` — workflow parsing and validation
- `src/agent_runtime/storage/sqlite.py` — persistence
- `src/agent_runtime/tools/` — built-in tool interfaces and discovery
- `src/agent_runtime/llm/` — provider registry and adapters

If you are new to the internals, start with [Architecture](architecture.md) and then skim the [Execution Walkthrough](../guide/execution-walkthrough.md).
