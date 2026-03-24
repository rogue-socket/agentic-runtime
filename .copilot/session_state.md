# Current Session State

## Current Feature / Task
Refresh stale workspace guidance in `.copilot/` and `.github/prompts/` so future sessions align with the current codebase and TODO governance.

## Progress Completed
- Audited all files in `.copilot/` and `.github/prompts/`.
- Reconciled guidance against current source/docs (`README.md`, `vision/todos.md`, latest changelog).
- Updated instruction/context files for workflow-first architecture (`agent`/`function`/`tool`) and deprecated `model` step compatibility.
- Added explicit TODO policy requiring categorized TODO tags from repo taxonomy.
- Appended ADR documenting categorized TODO governance.

## Files Modified In This Session
- `.copilot/instructions.md`
- `.copilot/project_context.md`
- `.copilot/resume_prompt.md`
- `.copilot/session_state.md`
- `.copilot/working_set.md`
- `.copilot/architecture_decisions.md`
- `.github/prompts/start-session.prompt.md`
- `.github/prompts/switch-session.prompt.md`
- `.github/prompts/wrap-session.prompt.md`

## Key Implementation Details
- Source-of-truth references now target `docs/about/*`, `docs/changelog/*`, and `vision/todos.md`.
- Canonical local Python environment is conda env `agent_runtime`.
- TODO governance standardized to:
	- `TODO(roadmap): ...`
	- `TODO(pain-point): ...`
	- `TODO(ux): ...`
	- `TODO(security): ...`
	- `TODO(eng): ...`
	- optional milestone tags (for example `TODO(0.2.0): ...`) for release-gated work.
- Prompt templates now remind contributors to add categorized TODOs when intentionally deferring implementation detail.

## Remaining Work
- Run a light sanity pass for stale references in edited prompt/context files.
- Optional follow-up: add CI lint/check for TODO category format.

## Known Issues / Open Questions
1. No automated CI validation currently enforces TODO tag taxonomy consistency.
2. Procedural memory is still roadmap-level and docs should be revisited when implemented.

## Recommended Next Step
1. If further docs cleanup is needed, run a targeted path/reference audit.
2. For any behavioral/runtime code changes, run `pytest -q` before wrap-up.
