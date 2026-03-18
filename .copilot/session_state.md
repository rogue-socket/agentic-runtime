# Current Session State

## Current Feature / Task
**Documentation refresh and codebase audit** — updating all prompt files, docs, and changelogs to reflect the current state of the runtime as of 2026-03-18.

## Prior Session Summary (2026-03-17)

### Security Hardening
- FileTool `_safe_path` prefix bypass — fixed
- `import_agent` symlink/traversal attack — reject tar symlinks/hardlinks, validate manifest paths

### State Management
- Overwrite policy — configurable warn/strict/allow via RuntimeConfig
- StructuredLogger replaces print() for warnings

### Memory Tier Implementation
- WorkingMemory — full: scratch store (byte budget), sliding window, active task tracking
- SemanticMemory — full: SQLite + FTS5, CRUD, full-text search, tag retrieval
- MemoryManager — namespaced hydration under runtime.memory.<tier> with deep-merge
- ProceduralMemory — stub with roadmap

### Infrastructure & Packaging
- ShellTool allowlist/denylist (regex-based)
- Lifecycle hooks (EventCallback) — 5 lifecycle points
- pyproject.toml — setuptools backend, `ai` entry point
- Config wiring — memory limits, shell restrictions, default LLM provider

### SDK & CLI Ergonomics
- run_workflow() / run_workflow_async() SDK surface
- _coerce_value() for CLI input type parsing
- `ai init` full runtime.yaml template
- `ai onboard` / `ai setup` interactive wizard

## Session 2026-03-18 Changes

### Timing Telemetry
- Per-step duration computed before event emission
- handler_duration_ms / tool_duration_ms captured per step
- Run-level total duration from start/completion timestamps

### Visualization Enhancements
- HTML/ASCII show run summary (start, completion, total duration)
- Per-step call durations in output
- HTML tool tables include tool latency

### CLI Progress Output
- `ai run` prints `n/a` instead of `None` for missing values
- Includes call duration when available

### Documentation Refresh (this session)
- Updated .copilot/ prompt files to reflect current state
- Updated .github/prompts/ with current doc references
- Updated docs/ARCHITECTURE.md (memory, config, lifecycle hooks sections)
- Fixed docs/ONBOARDING_WALKTHROUGH.md hardcoded path
- Updated docs/GAPS_2026-03-17.md with resolution status
- Updated docs/STATUS_2026-03-17.md memory section
- Created complete CHANGELOG_2026-03-18.md

### UX
- `ai visualize --html` auto-opens browser (--no-open to disable)
- Added .runs/ to .gitignore

## Files Modified This Session
| File | Change |
|------|--------|
| `.copilot/instructions.md` | Updated security areas, added memory/lifecycle/overwrite notes |
| `.copilot/project_context.md` | Updated subsystem status, pyproject.toml, memory/architecture |
| `.copilot/session_state.md` | Full rewrite for 2026-03-18 |
| `.copilot/working_set.md` | Updated focus area and priorities |
| `.copilot/resume_prompt.md` | Updated with 2026-03-18 state |
| `.copilot/architecture_decisions.md` | Added ADR-004 through ADR-007 |
| `.github/prompts/start-session.prompt.md` | Updated doc references |
| `docs/ARCHITECTURE.md` | Updated memory, config, added lifecycle hooks section |
| `docs/ONBOARDING_WALKTHROUGH.md` | Fixed hardcoded absolute path |
| `docs/GAPS_2026-03-17.md` | Updated gap resolution status |
| `docs/STATUS_2026-03-17.md` | Updated memory subsystem status |
| `docs/CHANGELOG_2026-03-18.md` | Complete changelog |

## Known Issues or Open Questions
1. **Tests not yet validated** — all changes need `pytest tests/ -v` (no test infra available currently)
2. `type: model` vs `type: llm` step types — coexistence intent unclear
3. `_meta` tracking in RuntimeState (`written_by`) is dead metadata — never read
4. SAVEPOINT support for true nested transactions — left as TODO
5. Semantic memory vector-similarity retrieval (embeddings) not yet implemented
6. Procedural memory — stub only
7. LLM streaming event not yet implemented
8. docs/ONBOARDING_WALKTHROUGH.md had hardcoded macOS path — fixed to relative

## Remaining TODOs (Categorized)

### Blocking / P0
- **Run test suite** — `pytest tests/ -v` (blocked: no test infra)

### P1 — Actionable
- Secret redaction for sensitive fields (`cli.py`)
- LLM handler E2E tests with mocked client
- OpenAI adapter unit tests
- Example LLM workflow YAML (05_llm_call.yaml needs verification)

### P2 — Roadmap
- Procedural memory implementation
- Vector-similarity retrieval for semantic memory
- LLM streaming / token-level feedback
- Multi-agent composition — step invokes sub-workflow
- SAVEPOINT for nested transactions
- PostgreSQL storage backend
- OpenTelemetry / Prometheus observability
- Interactive graph rendering in HTML visualization
- Parallel step execution / DAG scheduler
- Circular branching detection
1. **Run tests** — `pytest tests/ -v` — validates all session changes
2. **Secret redaction** — small, high-value security improvement
3. **LLM handler test** — mock-based E2E test for the LLM step handler
4. **Example LLM workflow** — `workflows/samples/05_llm_call.yaml`
5. **Procedural memory** — now unblocked by episodic + semantic
6. **LLM streaming** — adapter-level chunked response + `LLM_TOKEN` event
