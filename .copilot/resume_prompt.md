# Resume Prompt

Project: ForrestRun

Before writing code, read in this order:
1. `.copilot/project_context.md`
2. `.copilot/session_state.md`
3. `.copilot/working_set.md`
4. `planning/vision/todos.md`
5. `documentation/changelog/CHANGELOG_2026-03-31.md`

Execution reminders:
- Workflow steps use `agent`, `function`, and `tool`.
- Runtime state remains namespaced as `inputs`, `steps`, `runtime`.
- Replay/resume guarantees depend on workflow hash checks and durable storage writes.

Environment reminders:
- Prefer `conda activate wa-data` in this workspace if available.
- If unavailable, use repository-default docs guidance (`agent_runtime`).

TODO reminders:
- Use categorized TODOs only: `roadmap`, `pain-point`, `ux`, `security`, `eng`.
- For intentional partial implementations, add an inline categorized TODO at the decision point.

Session objective template:
- Confirm current objective from `.copilot/session_state.md`.
- Implement minimal, scoped changes.
- Validate behavior with targeted tests when practical.
- Update `.copilot/session_state.md` and `.copilot/working_set.md` before ending.
