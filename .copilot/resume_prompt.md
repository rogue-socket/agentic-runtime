# Resume Prompt

Project: `agentic-runtime` (deterministic runtime for workflow-based AI execution).

Before coding, read in this order:
1. `.copilot/project_context.md`
2. `.copilot/session_state.md`
3. `.copilot/working_set.md`
4. `vision/todos.md`
5. `docs/changelog/CHANGELOG_2026-03-23.md`

Execution model reminder:
- Workflows orchestrate `agent`, `function`, and `tool` steps.
- State is namespaced (`inputs`, `steps`, `runtime`) and persisted per step.
- Resume/replay determinism depends on storage integrity and workflow hashing.

Environment reminder:
- Activate conda env before running commands: `conda activate agent_runtime`.

TODO convention reminder:
- Use categorized TODOs only: `roadmap`, `pain-point`, `ux`, `security`, `eng`.
- If an implementation is intentionally partial or simplified, add an inline categorized TODO at the decision point.

Session objective template:
- Confirm current task and touched modules from `.copilot/session_state.md`.
- Implement scoped changes in `src/agent_runtime/...`.
- Validate with targeted tests (or full `pytest -q` when feasible).
- Update `.copilot/session_state.md` and `.copilot/working_set.md` before ending.
