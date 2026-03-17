# Current Session State

## Current Feature / Task
**Comprehensive runtime hardening and feature buildout** — security fixes, state management, memory tiers, lifecycle hooks, packaging, SDK surface, CLI ergonomics.

## Current Progress (Session 2026-03-17)

### Security Hardening — DONE
- **FileTool `_safe_path` prefix bypass** — fixed sibling-directory bypass (e.g. `/projectx` matching `/project`)
- **`import_agent` symlink/traversal attack** — reject tar symlinks/hardlinks, `_safe_copy` validates all manifest paths against project root

### State Management — DONE
- **Overwrite policy** — replaced `print()` warnings with `StructuredLogger`; configurable `warn`/`strict`/`allow` policy threaded through `RuntimeConfig` → `Executor` → `RunState` → `RuntimeState`

### Memory Tier Implementation — DONE
- **Fixed `hydrate_state` namespace corruption** — deep-merge under `runtime.memory.<tier>` instead of `dict.update` on top-level state
- **WorkingMemory** — full implementation: scratch key-value store with byte budget, sliding window context entries, active task tracking, auto-capture step output, `reset()` for run-end cleanup
- **SemanticMemory** — SQLite + FTS5: CRUD with upsert, full-text search (BM25 ranking), tag-based retrieval, protocol-driven hydration/persistence, backward-compatible stub mode
- **MemoryManager** — `_tiers()` iterator, `_deep_merge` helper, namespaced hydration
- **ProceduralMemory** — stub with updated roadmap (episodic + semantic prerequisites met)

### Infrastructure & Packaging — DONE
- **ShellTool allowlist/denylist** — regex-based pattern matching on extracted program name via `shlex.split`
- **Lifecycle hooks / event system** — `EventCallback` type, `on_event` on Executor, emits `RUN_START`/`STEP_START`/`STEP_COMPLETE`/`STEP_ERROR`/`RUN_COMPLETE`
- **`pyproject.toml`** — setuptools backend, `ai` CLI entry point, Python 3.10-3.13 classifiers
- **Config wiring** — working memory limits, shell restrictions, default LLM provider in `RuntimeConfig` + `runtime.yaml`
- **LLM default provider** — `LLMRegistry.default_provider` resolves ambiguous model references

### SDK & CLI Ergonomics — DONE
- **SDK convenience functions** — `run_workflow()` and `run_workflow_async()` in `__init__.py`; handles config, storage, memory, registries, and executor construction internally
- **CLI input type coercion** — `_coerce_value()` auto-parses `-i key=value` args (bool, int, float, JSON, str fallback)
- **`ai init` template** — complete `runtime.yaml` template with all config sections documented (storage, directories, overwrite policy, LLM providers, memory limits, shell restrictions, logging)

## Files Modified This Session
| File | Change |
|------|--------|
| `src/agent_runtime/__init__.py` | `run_workflow()`, `run_workflow_async()`, exported `EventCallback` + SDK functions |
| `src/agent_runtime/cli.py` | `_coerce_value()`, expanded `RUNTIME_YAML_TEMPLATE`, full config wiring, SemanticMemory db_path |
| `src/agent_runtime/config.py` | `overwrite_policy`, memory limits, shell restrictions, `default_llm_provider` |
| `src/agent_runtime/core.py` | `EventCallback`, `on_event` lifecycle hooks, `overwrite_policy` threading |
| `src/agent_runtime/state.py` | `StructuredLogger`, configurable `overwrite_policy` (warn/strict/allow) |
| `src/agent_runtime/tools/file.py` | Fixed `_safe_path` prefix bypass |
| `src/agent_runtime/tools/shell.py` | Allowlist/denylist with regex pattern matching |
| `src/agent_runtime/agent/packaging.py` | Reject symlinks/hardlinks, validate manifest paths |
| `src/agent_runtime/memory/base.py` | Namespaced hydration with deep-merge, `_tiers()` iterator |
| `src/agent_runtime/memory/working.py` | Full implementation: scratch, entries, active task |
| `src/agent_runtime/memory/semantic.py` | Full implementation: SQLite + FTS5, tags, CRUD, protocol hydration |
| `src/agent_runtime/memory/procedural.py` | Updated TODO roadmap |
| `src/agent_runtime/llm/registry.py` | `default_provider` property on `LLMRegistry` |
| `src/agent_runtime/llm/client.py` | Use `default_provider` for ambiguous model resolution |
| `requirements.txt` | Updated comments (pyproject.toml is now canonical) |
| `pyproject.toml` | NEW: package metadata, `ai` entry point, setuptools backend |

## Key Implementation Details
- `SQLiteStorage` uses `isolation_level=None` (autocommit) with manual `BEGIN`/`COMMIT`/`ROLLBACK`
- `transaction()` is reentrant: nested calls absorbed by outermost (no savepoints yet)
- Executor wraps step persistence atomically via `storage.transaction()`
- `EventCallback = Callable[[str, Dict[str, Any]], None]` — fires at 5 lifecycle points
- ShellTool uses `re.fullmatch` on extracted first token for allow/deny checks
- `run_workflow()` is a one-call sync API; `run_workflow_async()` is the async equivalent
- `_coerce_value()` tries bool → int → float → JSON → str, left-to-right
- Semantic memory FTS5 index uses `tokenize='porter unicode61'` for prefix search
- Tests have **not been run yet** — need full `pytest tests/ -v`

## Known Issues or Open Questions
1. **Tests not yet validated** — all changes need `pytest tests/ -v`
2. `type: model` vs `type: llm` step types — coexistence intent unclear
3. `asyncio.run()` guard exists but no automatic fallback helper for async callers
4. `_meta` tracking in `RuntimeState` (`written_by`) is dead metadata — never read
5. SAVEPOINT support for true nested transactions — left as TODO
6. Semantic memory vector-similarity retrieval (embeddings) not yet implemented
7. Procedural memory — stub only, roadmap updated with concrete design
8. LLM streaming event not yet implemented (requires adapter-level chunked parsing)
9. SDK `__init__.py` TODO comment still references broader API design work

## Remaining TODOs (Categorized)

### Blocking / P0
- **Run test suite** — `pytest tests/ -v`

### P1 — Actionable
- Secret redaction for sensitive fields (`cli.py`)
- LLM handler E2E tests with mocked client (`handler.py`)
- OpenAI adapter unit tests (`adapters.py`)
- Example LLM workflow YAML (`handler.py`)
- Template escaping and error context (`utils.py`)

### P2 — Roadmap
- Procedural memory implementation (`procedural.py`)
- Vector-similarity retrieval for semantic memory (`semantic.py`)
- LLM streaming / token-level feedback (`adapters.py`)
- Multi-agent composition — step invokes sub-workflow (`core.py`)
- SAVEPOINT for nested transactions (`sqlite.py`)
- PostgreSQL storage backend (`base.py`)
- OpenTelemetry / Prometheus observability (`logging.py`)
- Interactive graph rendering in HTML visualization (`html_renderer.py`)
- Parallel step execution / DAG scheduler (`core.py`)
- Circular branching detection (`core.py`, `resume.py`)

## Next Steps (Recommended Priority)
1. **Run tests** — `pytest tests/ -v` — validates all session changes
2. **Secret redaction** — small, high-value security improvement
3. **LLM handler test** — mock-based E2E test for the LLM step handler
4. **Example LLM workflow** — `workflows/samples/05_llm_call.yaml`
5. **Procedural memory** — now unblocked by episodic + semantic
6. **LLM streaming** — adapter-level chunked response + `LLM_TOKEN` event
