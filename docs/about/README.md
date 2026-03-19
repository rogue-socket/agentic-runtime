**About The Codebase**

This folder explains how the runtime is structured and how it behaves under the hood.

- `docs/about/architecture.md` — the execution model, data model, and extension points
- `docs/about/status_2026-03-17.md` — implementation status snapshot
- `docs/about/gaps_2026-03-17.md` — known gaps and planned work
- `docs/about/git_runtime_date.md` — source control date reference

**Where The Code Lives**

- `src/agent_runtime/cli.py` — CLI entrypoints and orchestration
- `src/agent_runtime/core.py` — executor and step execution logic
- `src/agent_runtime/workflow.py` — workflow parsing and validation
- `src/agent_runtime/storage/sqlite.py` — persistence
- `src/agent_runtime/tools/` — built-in tool interfaces and discovery
- `src/agent_runtime/llm/` — provider registry and adapters

If you are new to the internals, start with `docs/about/architecture.md` and then skim the execution walkthrough in `docs/guide/execution-walkthrough.md`.
