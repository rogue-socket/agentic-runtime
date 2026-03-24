# Copilot Instructions

When assisting with this repo:

- Follow architecture and status in `.copilot/project_context.md` first.
- Use these docs as source of truth: `docs/about/architecture.md`, `docs/about/gaps_2026-03-17.md`, `docs/changelog/CHANGELOG_2026-03-23.md`, and `vision/todos.md`.
- Prefer modifying existing modules over creating new files.
- Keep dependency footprint minimal. HTTP adapters use stdlib `urllib`; do not add `requests`/`httpx` unless explicitly approved.
- Preferred Python environment is conda env `agent_runtime`; activate it before running tests/CLI commands.
- `pyproject.toml` is canonical package metadata. Keep `requirements.txt` as a convenience mirror.
- Runtime state is namespaced: `inputs.*`, `steps.*`, `runtime.*`. Route state access through `RuntimeState` helpers.
- Keep step model aligned with current runtime:
	- `type: agent` for LLM reasoning via `agent/` definitions.
	- `type: function` for deterministic Python callables in `functions/`.
	- `type: tool` for Tool protocol implementations in `tools/`.
- Respect registry patterns (`ToolRegistry`, `LLMRegistry`, `WorkflowRegistry`, `AgentRegistry`).
- Tools must implement Tool protocol (`name`, `description`, `input_schema`, `execute`).
- Persist through `Storage` abstractions only; do not perform ad hoc SQLite access outside storage modules.
- Use `safe_eval()` for branch expressions; never introduce raw `eval`/`exec`.
- Use `StructuredLogger`; avoid `print()` in runtime paths.
- Internals are async-first with sync wrappers; avoid nested `asyncio.run()` patterns.
- Security-sensitive areas: `tools/file.py`, `tools/shell.py`, `agent/packaging.py`, `utils.py`, and branch expression validation.
- Memory hydration must remain namespaced under `runtime.memory.<tier>` with deep-merge semantics.
- Lifecycle events (`RUN_START`, `STEP_START`, `STEP_COMPLETE`, `STEP_ERROR`, `RUN_COMPLETE`) should remain stable unless intentionally versioned.

## TODO Policy (Important)

- When intentionally taking a short-term or partial implementation path, add a TODO immediately at the decision point.
- Use required format: `TODO(<category>): <summary>`.
- Allowed categories (from the codebase):
	- `roadmap`
	- `pain-point`
	- `ux`
	- `security`
	- `eng`
- Milestone tags like `TODO(0.2.0): ...` are allowed only for explicit release-gated work.
- TODOs must explain:
	- what was intentionally left incomplete,
	- why it was deferred,
	- and the expected follow-up direction.
- Do not add uncategorized TODO comments.

## Validation

- Environment setup: `conda activate agent_runtime`.
- Run tests from repo root: `pytest -q` (or targeted tests for touched modules).
- If tests cannot run, call that out explicitly in the session summary.
