# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ForrestRun** is an embeddable Python library for running AI agent workflows. Define agent pipelines in YAML mixing three step types — `agent` (LLM reasoning), `function` (deterministic Python), and `tool` (external actions) — with built-in persistence, replay, resume, branching, and multi-tier memory.

The primary interface is the Python SDK (`from agent_runtime import run_workflow`). A CLI (`ai`) is also provided for running, inspecting, and debugging workflows from the terminal.

Python 3.10+. Minimal dependencies (PyYAML, typing-extensions). All LLM adapters use stdlib `urllib` — no third-party HTTP libraries. PyPI package name: `forrestrun`.

## Build & Run Commands

```bash
# Install (development)
pip install -e ".[dev]"

# Run all tests (635 passing as of 2026-04-25)
pytest -q

# Run a single test file
pytest tests/test_runtime.py

# Run tests matching a keyword
pytest -k "test_replay"

# Lint (ruff configured in pyproject.toml)
ruff check src/ tests/

# SDK usage (primary interface)
from agent_runtime import run_workflow
result = run_workflow("workflows/example.yaml", inputs={...})

# CLI (secondary interface)
ai run workflows/example.yaml
ai inspect <run_id> --steps
ai resume <run_id>
ai replay <run_id> --verify-state
```

## Architecture

### Core Execution Model

The **Executor** (`core.py`) runs workflows step-by-step. Each step reads from and writes to a **namespaced RuntimeState** (`state.py`) with three top-level namespaces:
- `inputs.*` — request/context payload
- `steps.<step_id>.*` — per-step outputs (write boundaries enforced)
- `runtime.*` — metadata, memory tiers, timing

### Four Registries

All extensible components are managed through registries (plugin pattern):
- **AgentRegistry** — discovers agents from `agents/*.yaml`
- **ToolRegistry** — registers tool implementations (protocol: `name`, `description`, `input_schema`, `execute`)
- **WorkflowRegistry** — version-aware workflow resolution
- **LLMRegistry** — multi-provider adapters (OpenAI, Anthropic, Gemini)

### LLM Providers

Three provider adapters in `src/agent_runtime/llm/adapters.py`, all using `urllib.request` with exponential-backoff retry (`_urlopen_with_retry`):
- **OpenAIAdapter** — native `tool_calls` format, configurable `base_url`
- **AnthropicAdapter** — native `tool_use` with `input_schema`
- **GeminiAdapter** — native `functionCall` format, parameter aliasing (`max_tokens` → `maxOutputTokens`)

A **MockAdapter** exists for offline/test use (deterministic responses, no HTTP).

### Persistence & Recovery

SQLite backend with a single persistent connection and explicit transaction management. Every step's input, output, and state snapshot is persisted atomically. Workflow content hashing (SHA256 of raw YAML) blocks unsafe resumes — if the workflow changed since the failed run, resume is rejected with `WorkflowIntegrityError`.

### Memory Tiers

Four tiers hydrate under `runtime.memory.<tier>` with deep-merge semantics:
- **Working** — in-process scratch store with byte budget and sliding-window eviction. Fully implemented.
- **Episodic** — SQLite-backed run summaries with truncation. Fully implemented.
- **Semantic** — SQLite FTS5 full-text search with BM25 ranking, plus tag-based queries. Fully implemented.
- **Procedural** — key/value store with SQLite persistence. Minimal implementation — no auto-learning from episodic history yet (roadmap).

### Branch Conditions

`safe_eval()` in `utils.py` uses AST validation (`_SafeExprValidator`) to sandbox branch condition expressions. Supports comparisons, boolean logic, `len`/`min`/`max`/`abs`, and string methods. Used by the executor's `_resolve_next_step()` in `core.py` and `resume.py`. Never use raw `eval`/`exec`.

### Lifecycle Events

The Executor emits five events via `_emit()` callbacks during workflow execution:
- `RUN_START` — when workflow begins (payload: run_id, workflow_id)
- `STEP_START` — when a step begins (payload: run_id, step_id, step_type, attempt_count)
- `STEP_COMPLETE` — when a step succeeds (payload includes duration_ms, tool_duration_ms)
- `STEP_ERROR` — when a step fails (payload includes error, attempt_count)
- `RUN_COMPLETE` — when workflow finishes (payload: run_id, status, error)

These names are stable contracts. Used by CLI for progress display and by the debugger.

## Repository Layout

- `src/agent_runtime/` — core runtime engine (cli, core, workflow, state, config, agent/, llm/, memory/, storage/, tools/, visualization/)
- `examples/reference_project/` — bundled sample project (agents/, workflows/, functions/, tools/, prompts/)
- `tests/` — test suite (40+ files, 635 tests)
- `documentation/` — product docs, architecture, changelogs
- `planning/` — roadmap, feature designs

The repo is library-first. When users run `ai init`, the runtime scaffolds project directories in their target folder. The primary public API is `run_workflow()` / `run_workflow_async()` in `__init__.py`.

## Key Conventions

- **Async-first internals with sync wrappers** — avoid nested event-loop anti-patterns.
- **Persist via storage abstractions only** — no direct SQLite calls outside `storage/` (memory tiers are the exception — they own their own SQLite tables).
- **Workflow step types** (`agent`, `function`, `tool`) are distinct from **agent pipeline step types** (`model`, `tool`) — do not conflate them.
- **TODO governance** — all TODOs must use `TODO(<category>): ...` with categories: `roadmap`, `pain-point`, `ux`, `security`, `eng`. Milestone tags like `TODO(0.2.0)` are allowed.
- **Schema versioning** — baseline is `v1` for all YAML schemas and SQLite metadata. Minor bumps (`v1.1`) for component-local changes, major bumps (`v2`) for cross-system changes.

## Source-of-Truth Docs

Read before major edits:
1. `documentation/about/architecture.md` — execution model, state contract, persistence
2. `documentation/about/status_2026-03-17.md` — module inventory, implementation status
3. `documentation/about/gaps_2026-03-17.md` — known limitations
4. `documentation/changelog/CHANGELOG_2026-03-31.md` — recent changes
5. `planning/vision/todos.md` — prioritized backlog
