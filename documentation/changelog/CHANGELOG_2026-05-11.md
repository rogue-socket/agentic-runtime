# Changelog — 2026-05-11 (v0.2.1)

Bug-fix sweep from the v0.2.0 dogfood session. Six issues filed during e2e
testing on fresh PyPI installs (issues #7, #9, #10, #11, #15, #16) are
resolved here. No SDK or workflow-schema changes.

## Fixes

- **`ai resume <completed_run_id>` now returns AR-RUN-COMPLETED (#11).**
  Previously dumped a raw `StepExecutionError` traceback from
  `validate_resume`. Introduced `RunAlreadyCompletedError` and routed it
  through `_print_cli_exception` so the user sees:
  `Error [AR-RUN-COMPLETED]: Run has already finished and cannot be resumed.`

- **Function resolution failures now return AR-FUNCTION-RESOLUTION (#10).**
  All five `raise ValueError` sites in `function_resolver.py` (missing dir,
  malformed ref, missing module, missing attr, ambiguous match, import
  failure) converted to typed `FunctionResolutionError`. Missing-module
  message enriched with a create-or-fix hint. Workflow-load path catches
  `RuntimeErrorBase` so the AR-* formatter fires.

- **Bad branch expressions now return AR-BRANCH-RESOLUTION (#9).**
  `safe_eval` raised raw `SyntaxError`/`ValueError` on malformed `when`
  clauses; both `_resolve_next_step` call sites (core executor and resume)
  propagated unwrapped. Wrapped in `try/except` raising
  `BranchResolutionError` with the offending step id and rule text.

- **`ai metrics` no longer crashes on None outcome values (#7).**
  `dict.get('key', 0.0)` only returns the default when the key is missing;
  explicit `None` (which the aggregator writes for runs without outcome
  data) made `f"{None:.2%}"` raise `TypeError`. Read through a `_pct`
  helper that coalesces at the formatting boundary.

## Quality of life

- **`ai init` scaffolds a runnable hello-world (#15).**
  `workflows/hello.yaml` + `functions/hello.py` — function-only so it
  runs with no API key. `ai init && ai run workflows/hello.yaml` now
  succeeds end-to-end on a fresh project.

- **macOS SSL gotcha documented in README (#16).**
  Stdlib `urllib` has no CA bundle on fresh macOS Python installs and
  forrestrun's zero-dep design means there's no transitive `certifi`. Two
  workarounds documented under LLM Providers.

## Tests

- 818 passing locally (no count change; updated 2 assertions in
  `tests/test_resume.py` and 6 in `tests/test_pipeline_and_functions.py`
  to expect the new typed exceptions).

## Versioning

- Bumped `pyproject.toml` version from `0.2.0` to `0.2.1`.
