# Working Set

## Focus Area
Keep assistant/session scaffolding current with live runtime architecture and enforce TODO taxonomy consistency in future edits.

## Environment
- Use conda env `agent_runtime` for CLI/test execution context.

## Active Files
- `.copilot/instructions.md`
- `.copilot/project_context.md`
- `.copilot/session_state.md`
- `.copilot/working_set.md`
- `.copilot/resume_prompt.md`
- `.copilot/architecture_decisions.md`
- `.github/prompts/start-session.prompt.md`
- `.github/prompts/switch-session.prompt.md`
- `.github/prompts/wrap-session.prompt.md`

## High-Signal Runtime Modules
- `src/agent_runtime/core.py`: execution loop, retries, branching, telemetry
- `src/agent_runtime/workflow.py`: parsing + contract validation + compatibility rules
- `src/agent_runtime/cli.py`: command orchestration and UX behavior
- `src/agent_runtime/agent/`: agent definition/strategy/execution subsystem
- `src/agent_runtime/llm/`: provider registry, adapters, call routing
- `src/agent_runtime/tools/`: tool protocol + discovery + built-ins
- `src/agent_runtime/memory/`: working/episodic/semantic/procedural memory tiers
- `src/agent_runtime/storage/sqlite.py`: persistent storage and transactions

## Key Context Docs
- `README.md`
- `planning/vision/todos.md`
- `documentation/about/architecture.md`
- `documentation/changelog/CHANGELOG_2026-03-23.md`

## TODO Category Standard (Reference)
- `roadmap`
- `pain-point`
- `ux`
- `security`
- `eng`
- Optional milestone tags for release-targeted work (for example `0.2.0`)

## Test Anchors
- `tests/test_runtime.py`
- `tests/test_executor_e2e.py`
- `tests/test_cli.py`
- `tests/test_openai_adapter.py`
- `tests/test_tool_discovery.py`
- `tests/test_transaction_safety.py`
- `tests/test_workflow_versioning.py`

README currently reports: `pytest -q` with 448 passing tests.
