# Changelog — 2026-03-17

## Bug Fixes

### P0 — Correctness

- **`validate_input` required-field enforcement** (`tools/validation.py`):
  The JSON Schema validator ignored `required` arrays entirely. Tools declaring required fields (HttpTool: `url`, FileTool: `action`/`path`) accepted empty payloads and failed with confusing KeyErrors downstream. Now enforces `required` before type-checking, raising `ValueError("Missing required field: '<key>'")`.

- **`append_step` truthiness bug** (`storage/sqlite.py`):
  Empty dict payloads `{}` for `input`, `output`, `state_before`, and `state_after` were stored as `NULL` in SQLite due to `if step.X else None` treating `{}` as falsy. Changed to `if step.X is not None else None`. Empty dicts now roundtrip correctly, fixing replay accuracy and state-diff correctness.

- **Run stuck in RUNNING on unhandled error** (`core.py`):
  If `save_state`, `_resolve_next_step`, or JSON serialization threw after the step-level try/except, the exception escaped without updating run status. The run was permanently stuck as RUNNING and unrecoverable (resume rejects RUNNING runs). Split `_execute_steps_async` into a wrapper that catches unexpected errors and marks the run FAILED before re-raising.

- **Replay crashes on any run with a failed step** (`replay.py`):
  The replay loop unconditionally required `state_after is not None`, but failed steps have `state_after = None` by design. Any run containing a failed step — including `COMPLETED_WITH_ERRORS` — could not be replayed. Changed to only require `state_before`; when `state_after` is None, state carries forward unchanged.

- **`RunState.data` returns `MappingProxyType` when frozen** (`core.py`):
  After `run.freeze()`, `run.state.data` returned a `MappingProxyType`, not a `dict`. `json.dumps()` raised `TypeError` on the result. Changed to return `dict(current)` — a plain copy that's JSON-serializable. Removed unused `MappingProxyType` import.

### P1 — Branch Evaluation

- **`_DotDict` missing `__len__` and `__bool__`** (`utils.py`):
  Branch conditions using `len(state.inputs)` raised `TypeError` because `_DotDict` had no `__len__`. Empty dicts wrapped in `_DotDict` evaluated as truthy (Python default) causing wrong branch selection. Added both methods delegating to the wrapped data.

- **`_SafeExprValidator` rejects `not` operator** (`utils.py`):
  `ast.UnaryOp` was allowed but operator nodes (`ast.Not`, `ast.USub`, etc.) were not. Branch conditions like `not state.inputs.is_low` failed with `ValueError("Unsupported expression")`. Added `ast.Not`, `ast.USub`, `ast.UAdd`, `ast.Invert`, and arithmetic operators to the allowlist.

### P2 — Security Hardening

- **`_SafeExprValidator` blocks dunder attribute access** (`utils.py`):
  Added `visit_Attribute` method that rejects attribute names starting with `_`. Prevents expressions like `state.__init__.__globals__` from leaking the module's namespace through branch conditions.

## Security TODOs Added

- **FileTool `_safe_path` prefix bypass** (`tools/file.py`):
  `startswith(self.root)` is defeated by sibling directories sharing a prefix (e.g., `/project` vs `/projectx`). TODO documents the fix: `resolved == self.root or resolved.startswith(self.root + os.sep)`.

- **`import_agent` symlink + manifest path traversal** (`agent/packaging.py`):
  Two vulnerabilities: (1) tar symlink members bypass path validation, (2) manifest paths (`workflow`, `handlers`, `tools`) are joined to project_root without traversal checks. TODO documents both fixes.

## Product TODOs Added

Across 14 source files, tagged with categories:

| Tag | Files | What |
|---|---|---|
| `packaging` | `requirements.txt`, `README.md`, `config.py` | `pyproject.toml`, PyPI publishing, Makefile, single-binary distribution |
| `sdk` | `__init__.py` | Programmatic API: `run_workflow()`, async-first embedding |
| `ux` | `cli.py`, `config.py`, `README.md` | Solo dev ICP: `ai quickstart`, progress output, scaffolded LLM agent, input type coercion |
| `streaming` | `core.py` | `on_event` callback for real-time step/token progress |
| `testing` | `llm/adapters.py`, `llm/handler.py` | Missing OpenAI adapter test, LLM handler E2E test |
| `example` | `llm/handler.py` | Real-world `handler: llm` workflow sample |
| `roadmap` | `storage/base.py`, `logging.py`, `core.py`, memory tiers | Postgres backend, OpenTelemetry, Prometheus, multi-agent composition |

## Tests Added

- **`tests/test_builtin_tools.py`** — `TestValidateInput` (8 tests): missing required field, multiple required fields, present passes, None value passes, no required array, empty schema, HttpTool schema enforcement, FileTool schema enforcement.

- **`tests/test_storage_roundtrip.py`** — `TestAppendStepEmptyDict` (6 tests): empty input/output/state_before/state_after roundtrip, None stays None, populated dict roundtrip.

## Features

- **Gemini provider support** (`llm/adapters.py`, `llm/client.py`, `llm/__init__.py`):
  Added a Gemini adapter, request/response normalization, and client wiring.
  Sample workflow: `workflows/samples/06_gemini_call.yaml`.

- **Onboarding wizard** (`cli.py`, `docs/ONBOARDING_WALKTHROUGH.md`, `scripts/onboard.sh`):
  Added `ai` (no args) and `ai onboard` guided setup, plus a reusable onboarding script.

- **Setup enhancements** (`cli.py`):
  Added `ai setup --check` for provider/key verification and `.env` auto-loading.
