# Changelog — 2026-03-31

## Runtime Bug Fixes

- **Mock adapter tool-call contract alignment**:
  Fixed a runtime-breaking mismatch in `MockAdapter` where native tool calls were
  emitted with incorrect field names (`name`/`arguments`) instead of
  `ToolCallRequest`'s required `tool_name`/`tool_input` structure. This restores
  compatibility with the native tool-calling flow consumed by agent strategies.

- **Mock adapter history detection correction**:
  Updated mock ReAct history checks to recognize native `tool_results` entries
  and text fallback observations (`Tool observation:`). This prevents repeated
  tool-call turns after tool results are already available.

## Tests

- Added `tests/test_mock_adapter.py` with targeted regressions for:
  - valid native tool-call request shape,
  - transition to final answer after native `tool_results`,
  - transition to final answer after text observation history.

- Verified targeted adapter and phase tests in conda env `agent_runtime`:
  `84 passed`.

## Versioning

- Bumped package version from `0.1.0` to `0.1.1` in `pyproject.toml`.
