# Resume Prompt

## Project
agentic-runtime — deterministic local-first execution runtime for LLM-powered AI agent workflows.

## Architecture
YAML workflows → parser (workflow.py) → Executor (core.py) step loop → handlers/tools/LLM → SQLite persistence (storage/sqlite.py). State is namespaced `{inputs, steps, runtime}` with deep-copy snapshots at every step boundary. Lifecycle events emitted via `EventCallback`. Per-step and run-level timing telemetry captured.

## What's Implemented
- Core executor with retry, exponential backoff, conditional branching, resume, replay
- Per-step timing telemetry (handler_duration_ms, tool_duration_ms) and run-level duration
- YAML workflow parser with step validation, handler resolution, output contracts, workflow hashing
- CLI (`ai` command): init, onboard, setup, run, inspect, resume, replay, state-diff, visualize, validate, export, import, list (14 commands)
- Interactive onboarding wizard (`ai` no-args, `ai onboard`)
- SQLite storage with persistent connection, explicit transaction management (BEGIN/COMMIT/ROLLBACK), WAL mode
- LLM subsystem: provider registry with `default_provider`, OpenAI + Anthropic + Gemini adapters (urllib), client facade, built-in `llm` handler with prompt templating
- Tool framework: protocol, registry, auto-discovery, input validation, 4 built-in tools (echo, http, file, shell)
- **ShellTool** with regex-based allowlist/denylist command filtering
- **FileTool** with fixed path traversal protection (`_safe_path` with os.sep check)
- **Agent packaging** with symlink/hardlink rejection and path traversal validation
- **Memory system**: MemoryManager with namespaced hydration (runtime.memory.<tier>)
  - WorkingMemory: scratch store (byte budget), sliding window entries, active task tracking
  - SemanticMemory: SQLite + FTS5, CRUD, full-text search, tag retrieval, protocol-driven
  - EpisodicMemory: SQLite-backed event store
  - ProceduralMemory: stub with roadmap
- **State management**: configurable overwrite policy (warn/strict/allow), StructuredLogger
- **Lifecycle hooks**: EventCallback emitting RUN_START/STEP_START/STEP_COMPLETE/STEP_ERROR/RUN_COMPLETE
- **SDK surface**: `run_workflow()` (sync) and `run_workflow_async()` — one-call API with event loop detection
- **CLI ergonomics**: `_coerce_value()` for input type parsing, _redact() for secret filtering, complete `runtime.yaml` init template, .env auto-loading
- **Config**: RuntimeConfig with memory limits, shell restrictions, default LLM provider, overwrite policy
- **Packaging**: pyproject.toml with `ai` entry point, setuptools backend, v0.1.0 alpha
- Visualization: execution graph + timeline as HTML or ASCII with run/step timing and tool latency
- ~21 test files (NOT YET RUN)

## What's Still Missing
- **Tests not validated** — `pytest tests/ -v` must be run (no test infra currently)
- Secret redaction for sensitive fields in CLI output (partially implemented via _redact)
- LLM handler E2E tests, OpenAI adapter unit tests
- Procedural memory (stub → full implementation)
- Vector similarity for semantic memory
- LLM streaming / token-level feedback
- Multi-agent composition, parallel step execution
- SAVEPOINT for nested transactions
- PostgreSQL storage backend
- OpenTelemetry / Prometheus observability

## Current State
Session 2026-03-18: timing telemetry added (per-step + run-level), visualization enhancements (timing in HTML/ASCII), CLI progress improvements, `ai visualize --html` auto-opens, .runs/ in .gitignore. Full documentation refresh completed — all .copilot/, .github/prompts/, and docs/ files updated to reflect current codebase.

## Next Step
1. Run `pytest tests/ -v` to validate all changes (when test infra available)
2. Secret redaction (small, high-value)
3. LLM handler test + example workflow verification
4. Procedural memory implementation
