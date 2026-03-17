# Resume Prompt

## Project
agentic-runtime — deterministic local-first execution runtime for LLM-powered AI agent workflows.

## Architecture
YAML workflows → parser (workflow.py) → Executor (core.py) step loop → handlers/tools/LLM → SQLite persistence (storage/sqlite.py). State is namespaced `{inputs, steps, runtime}` with deep-copy snapshots at every step boundary. Lifecycle events emitted via `EventCallback`.

## What's Implemented
- Core executor with retry, exponential backoff, conditional branching, resume, replay
- YAML workflow parser with step validation, handler resolution, output contracts, workflow hashing
- CLI (`ai` command): init, run, inspect, resume, replay, state-diff, visualize, validate, export, import, list
- SQLite storage with persistent connection, explicit transaction management (BEGIN/COMMIT/ROLLBACK)
- LLM subsystem: provider registry with `default_provider`, OpenAI + Anthropic adapters (urllib), client facade, built-in `llm` handler with prompt templating
- Tool framework: protocol, registry, auto-discovery, input validation, 4 built-in tools (echo, http, file, shell)
- **ShellTool** with regex-based allowlist/denylist command filtering
- **FileTool** with fixed path traversal protection
- **Agent packaging** with symlink/hardlink rejection and path traversal validation
- **Memory system**: MemoryManager with namespaced hydration (runtime.memory.<tier>)
  - WorkingMemory: scratch store (byte budget), sliding window entries, active task tracking
  - SemanticMemory: SQLite + FTS5, CRUD, full-text search, tag retrieval, protocol-driven
  - EpisodicMemory: SQLite-backed event store
  - ProceduralMemory: stub with roadmap
- **State management**: configurable overwrite policy (warn/strict/allow), StructuredLogger
- **Lifecycle hooks**: EventCallback emitting RUN_START/STEP_START/STEP_COMPLETE/STEP_ERROR/RUN_COMPLETE
- **SDK surface**: `run_workflow()` (sync) and `run_workflow_async()` — one-call API
- **CLI ergonomics**: `_coerce_value()` for input type parsing, complete `runtime.yaml` init template
- **Config**: RuntimeConfig with memory limits, shell restrictions, default LLM provider, overwrite policy
- **Packaging**: pyproject.toml with `ai` entry point, setuptools backend
- Visualization: execution graph + timeline as HTML or ASCII
- ~19 test files (NOT YET RUN)

## What's Still Missing
- **Tests not validated** — `pytest tests/ -v` must be run
- Secret redaction for sensitive fields in CLI output
- LLM handler E2E tests, OpenAI adapter unit tests
- Example LLM workflow YAML (05_llm_call.yaml)
- Procedural memory (stub → full implementation)
- Vector similarity for semantic memory
- LLM streaming / token-level feedback
- Multi-agent composition, parallel step execution
- SAVEPOINT for nested transactions
- PostgreSQL storage backend
- OpenTelemetry / Prometheus observability

## Current State
Session 2026-03-17 completed: security hardening, state management, memory tiers (working + semantic), lifecycle hooks, ShellTool allowlist, pyproject.toml, config wiring, SDK surface, CLI input coercion, init template. All files compile without errors. Tests not yet run.

## Next Step
1. Run `pytest tests/ -v` to validate all changes
2. Secret redaction (small, high-value)
3. LLM handler test + example workflow
4. Procedural memory implementation
