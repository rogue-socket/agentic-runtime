**About The Codebase**

This folder explains how the runtime is structured and how it behaves under the hood.

- [Architecture](architecture.md) — the execution model, data model, and extension points
- [Evolution](evolution.md) — how and why the runtime's design changed
- [Status](status_2026-03-17.md) — implementation status snapshot (updated 2026-03-20)
- [Gaps](gaps_2026-03-17.md) — known gaps and planned work
- [Product Positioning](git_runtime_date.md) — runtime vs "Git for agents" positioning analysis

**Where The Code Lives**

- `src/agent_runtime/cli.py` — CLI entrypoints and orchestration
- `src/agent_runtime/core.py` — executor and step execution logic
- `src/agent_runtime/workflow.py` — workflow parsing and validation
- `src/agent_runtime/agent/` — agent definitions, strategies, pipelines, prompts
- `src/agent_runtime/llm/` — provider registry, adapters (OpenAI, Anthropic, Gemini)
- `src/agent_runtime/memory/` — multi-tier memory (working, episodic, semantic, procedural)
- `src/agent_runtime/storage/sqlite.py` — persistence
- `src/agent_runtime/tools/` — built-in tool interfaces and discovery
- `src/agent_runtime/visualization/` — run visualization (HTML + ASCII)

If you are new to the internals, start with [Architecture](architecture.md) and then skim the [Execution Walkthrough](../guide/execution-walkthrough.md).
