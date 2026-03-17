# Working Set

## Focus Area
Session complete. All planned work (security, state management, memory tiers, SDK surface, CLI ergonomics) is implemented. Next focus: test validation, then P1 TODOs (secret redaction, LLM tests, example workflow).

## Files Modified (Session 2026-03-17)
| File | Change |
|------|--------|
| `src/agent_runtime/__init__.py` | `run_workflow()` / `run_workflow_async()` SDK surface, `EventCallback` export |
| `src/agent_runtime/cli.py` | `_coerce_value()`, expanded `RUNTIME_YAML_TEMPLATE`, full config wiring |
| `src/agent_runtime/config.py` | `overwrite_policy`, memory limits, shell restrictions, `default_llm_provider` |
| `src/agent_runtime/core.py` | `EventCallback`, `on_event` lifecycle hooks, `overwrite_policy` threading |
| `src/agent_runtime/state.py` | `StructuredLogger`, configurable overwrite policy |
| `src/agent_runtime/tools/file.py` | Fixed `_safe_path` prefix bypass |
| `src/agent_runtime/tools/shell.py` | Allowlist/denylist with regex pattern matching |
| `src/agent_runtime/agent/packaging.py` | Reject symlinks/hardlinks, validate manifest paths |
| `src/agent_runtime/memory/base.py` | Namespaced hydration, deep-merge, `_tiers()` iterator |
| `src/agent_runtime/memory/working.py` | Full implementation: scratch, sliding window, active task |
| `src/agent_runtime/memory/semantic.py` | Full implementation: SQLite + FTS5, tags, CRUD |
| `src/agent_runtime/memory/procedural.py` | Updated TODO roadmap |
| `src/agent_runtime/llm/registry.py` | `default_provider` property |
| `src/agent_runtime/llm/client.py` | Use `default_provider` for ambiguous model resolution |
| `requirements.txt` | Updated comments |
| `pyproject.toml` | NEW: package metadata, `ai` CLI entry point |

## Primary Modules (Next Session)
| Module | Role | Priority |
|--------|------|----------|
| `tests/` | Test suite — not yet run | **High** |
| `src/agent_runtime/cli.py` | Secret redaction TODO | Medium |
| `src/agent_runtime/llm/handler.py` | LLM handler — needs E2E test | Medium |
| `src/agent_runtime/llm/adapters.py` | OpenAI adapter — needs unit test | Medium |
| `src/agent_runtime/memory/procedural.py` | Procedural memory — stub, unblocked | Medium |
| `workflows/samples/` | Need `05_llm_call.yaml` example | Low |

## Core Files (Reference)
- `src/agent_runtime/core.py` — Executor, Run/StepExecution, lifecycle hooks
- `src/agent_runtime/state.py` — RuntimeState with overwrite policy
- `src/agent_runtime/config.py` — RuntimeConfig with all settings
- `src/agent_runtime/__init__.py` — SDK public API surface
- `src/agent_runtime/storage/sqlite.py` — SQLiteStorage with transactions
- `src/agent_runtime/workflow.py` — YAML workflow parser
- `src/agent_runtime/steps.py` — StepHandler protocol + built-in handlers

## Related Tests
| Test File | Coverage |
|-----------|----------|
| `tests/test_transaction_safety.py` | Transaction commit/rollback/nesting/executor |
| `tests/test_runtime.py` | Core execution, retry, state versioning |
| `tests/test_resume.py` | Resume from failed step |
| `tests/test_replay.py` | Deterministic replay |
| `tests/test_state_manager.py` | RuntimeState operations |
| `tests/test_builtin_tools.py` | Tool input validation |
| `tests/test_storage_roundtrip.py` | Storage persistence |
| `tests/test_branching.py` | Conditional branching |
| `tests/test_visualization.py` | HTML/ASCII visualization |
| `tests/test_episodic_memory.py` | Episodic memory store |
- tests/test_storage_roundtrip.py — SQLite empty-dict roundtrip (6 tests)
- tests/test_state_manager.py — RuntimeState operations
- tests/test_state_diff.py — state diffing
- tests/test_state_history.py — state version tracking
- tests/test_step_contracts.py — output contract enforcement
- tests/test_visualization.py — graph/timeline rendering
- tests/test_workflow_versioning.py — version resolution
- tests/test_workflow_lock.py — workflow hash integrity
- tests/test_llm_registry.py — LLM provider registry
- tests/test_anthropic_adapter.py — Anthropic adapter
- tests/test_episodic_memory.py — episodic memory CRUD
- tests/test_agent_manifest.py — manifest validation
- tests/test_retry_policy.py — retry/backoff logic
- tests/test_branch_resume.py — branch + resume interaction

## Dependencies
- PyYAML — YAML parsing
- typing-extensions — protocol/type support
- pytest — testing
- Python stdlib: sqlite3, urllib, asyncio, argparse, json, hashlib, ast, copy, os, pathlib
