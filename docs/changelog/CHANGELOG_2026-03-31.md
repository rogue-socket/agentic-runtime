# Changelog — 2026-03-31

## Sample Contract Fixes (v0.1.2)

- **Agent+function sample input alignment**:
  Updated `workflows/samples/07_agent_and_function.yaml` so the `summarize`
  step maps `issue: inputs.text` to match `agents/summarizer.yaml` prompt
  expectations (`{{ inputs.issue }}`).

- **Regression guard for sample drift**:
  Added a focused test in `tests/test_workflow_file_coverage.py` to assert the
  sample's summarize step preserves this mapping contract.

- **Versioning**:
  Bumped package version from `0.1.1` to `0.1.2` in `pyproject.toml`.

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
