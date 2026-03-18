# Working Set

## Focus Area
Documentation refresh complete (2026-03-18). All .copilot/, .github/prompts/, and docs/ files updated to reflect current codebase state. Next focus: test validation (when infra available), then P1 TODOs (secret redaction, LLM tests).

## Files Modified (Session 2026-03-18)
| File | Change |
|------|--------|
| `.copilot/instructions.md` | Added pyproject.toml, security areas, memory/lifecycle/overwrite notes |
| `.copilot/project_context.md` | Updated subsystem status table, architecture, packaging status |
| `.copilot/session_state.md` | Full rewrite for 2026-03-18 session |
| `.copilot/working_set.md` | Updated focus area and priorities |
| `.copilot/resume_prompt.md` | Updated with 2026-03-18 state |
| `.copilot/architecture_decisions.md` | Added ADR-004 through ADR-007 |
| `.github/prompts/start-session.prompt.md` | Updated doc references |
| `docs/ARCHITECTURE.md` | Updated memory, config, lifecycle hooks sections |
| `docs/ONBOARDING_WALKTHROUGH.md` | Fixed hardcoded absolute path |
| `docs/GAPS_2026-03-17.md` | Updated gap resolution status |
| `docs/STATUS_2026-03-17.md` | Updated memory subsystem status |
| `docs/CHANGELOG_2026-03-18.md` | Complete changelog |

## Primary Modules (Next Session)
| Module | Role | Priority |
|--------|------|----------|
| `tests/` | Test suite — not yet run | **High** |
| `src/agent_runtime/cli.py` | Secret redaction TODO | Medium |
| `src/agent_runtime/llm/handler.py` | LLM handler — needs E2E test | Medium |
| `src/agent_runtime/llm/adapters.py` | OpenAI adapter — needs unit test | Medium |
| `src/agent_runtime/memory/procedural.py` | Procedural memory — stub, unblocked | Medium |

## Core Files (Reference)
- `src/agent_runtime/core.py` — Executor, Run/StepExecution, lifecycle hooks, timing telemetry
- `src/agent_runtime/state.py` — RuntimeState with overwrite policy (warn/strict/allow)
- `src/agent_runtime/config.py` — RuntimeConfig with all settings (memory, shell, LLM, overwrite)
- `src/agent_runtime/__init__.py` — SDK public API surface (run_workflow, run_workflow_async)
- `src/agent_runtime/storage/sqlite.py` — SQLiteStorage with persistent connection + transactions
- `src/agent_runtime/workflow.py` — YAML workflow parser with contracts + versioning
- `src/agent_runtime/steps.py` — StepHandler protocol + built-in handlers
- `src/agent_runtime/memory/base.py` — MemoryManager with namespaced deep-merge hydration
- `src/agent_runtime/memory/working.py` — WorkingMemory (scratch, entries, active task)
- `src/agent_runtime/memory/semantic.py` — SemanticMemory (SQLite + FTS5)
- `src/agent_runtime/tools/shell.py` — ShellTool with allowlist/denylist
- `src/agent_runtime/tools/file.py` — FileTool with safe path traversal protection
- `src/agent_runtime/visualization/` — Graph/timeline builders, ASCII + HTML renderers

## Related Tests
| Test File | Coverage |
|-----------|----------|
| `tests/test_runtime.py` | Core execution, retry, state versioning |
| `tests/test_transaction_safety.py` | Transaction commit/rollback/nesting/executor |
| `tests/test_resume.py` | Resume from failed step |
| `tests/test_replay.py` | Deterministic replay |
| `tests/test_branching.py` | Conditional branching |
| `tests/test_branch_resume.py` | Branch + resume interaction |
| `tests/test_state_manager.py` | RuntimeState operations |
| `tests/test_state_diff.py` | State diffing |
| `tests/test_state_history.py` | State version tracking |
| `tests/test_step_contracts.py` | Output contract enforcement |
| `tests/test_builtin_tools.py` | Tool input validation (8 tests) |
| `tests/test_storage_roundtrip.py` | SQLite empty-dict roundtrip (6 tests) |
| `tests/test_visualization.py` | Graph/timeline rendering |
| `tests/test_workflow_versioning.py` | Version resolution |
| `tests/test_workflow_lock.py` | Workflow hash integrity |
| `tests/test_llm_registry.py` | LLM provider registry |
| `tests/test_anthropic_adapter.py` | Anthropic adapter |
| `tests/test_gemini_adapter.py` | Gemini adapter |
| `tests/test_episodic_memory.py` | Episodic memory CRUD |
| `tests/test_agent_manifest.py` | Manifest validation |
| `tests/test_retry_policy.py` | Retry/backoff logic |

## Dependencies
- PyYAML — YAML parsing
- typing-extensions — protocol/type support
- pytest, pytest-asyncio — testing
- Python stdlib: sqlite3, urllib, asyncio, argparse, json, hashlib, ast, copy, os, pathlib, shlex, re
