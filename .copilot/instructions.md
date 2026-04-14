# Copilot Instructions

When assisting with this repository:

- Read in this order before major edits:
	1. `.copilot/project_context.md`
	2. `.copilot/session_state.md`
	3. `.copilot/working_set.md`
	4. `planning/vision/todos.md`
- Use these source-of-truth docs first:
	- `documentation/about/architecture.md`
	- `documentation/about/status_2026-03-17.md`
	- `documentation/about/gaps_2026-03-17.md`
	- `documentation/changelog/CHANGELOG_2026-03-31.md`
	- `planning/vision/todos.md`
- Prefer editing existing modules over creating new files unless a new file is clearly warranted.
- Keep dependencies minimal. LLM adapters should continue using stdlib `urllib`.
- Runtime state contract is namespaced and strict: `inputs.*`, `steps.*`, `runtime.*`.
- Primary workflow step types are `agent`, `function`, `tool`.
- Agent pipeline step types are separate (`model`, `tool`) and should not be conflated with workflow step types.
- Preserve registry-first architecture:
	- `AgentRegistry`
	- `ToolRegistry`
	- `LLMRegistry`
	- `WorkflowRegistry`
- Keep tool implementations aligned with the Tool protocol (`name`, `description`, `input_schema`, `execute`).
- Persist via storage abstractions only; avoid direct SQLite calls outside storage modules.
- Keep branch conditions sandboxed through `safe_eval()`; never introduce raw `eval`/`exec`.
- Maintain async-first internals with sync wrappers; avoid nested event-loop anti-patterns.
- Preserve memory hydration namespacing under `runtime.memory.<tier>` using deep-merge semantics.
- Keep lifecycle event names stable unless intentionally versioned:
	- `RUN_START`
	- `STEP_START`
	- `STEP_COMPLETE`
	- `STEP_ERROR`
	- `RUN_COMPLETE`

## Environment Notes

- If available locally, prefer conda env `wa-data` for command execution in this workspace.
- Repository docs may still reference `agent_runtime`; treat that as project-default guidance.

## TODO Policy

- For intentional deferrals or partial implementations, add a TODO at the decision point.
- Required format: `TODO(<category>): <summary>`.
- Allowed categories:
	- `roadmap`
	- `pain-point`
	- `ux`
	- `security`
	- `eng`
- Milestone tags like `TODO(0.2.0): ...` are allowed for explicit release-gated work.
- Avoid uncategorized TODOs.

## Validation Expectations

- Run targeted tests for changed behavior when practical.
- If tests are skipped or cannot run, explicitly note that in session summary.
