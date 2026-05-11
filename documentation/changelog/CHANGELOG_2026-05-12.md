# Changelog — 2026-05-12 (v0.2.2)

Follow-up to v0.2.1 closing the remaining issues from the dogfood session
(#8, #12, #13, #14) plus one paper cut surfaced during real-workflow
dogfood. No SDK or workflow-schema changes.

## Fixes

- **`ai metrics` no longer reports `LLM total tokens: 0` for Gemini runs (#8).**
  The storage aggregator and three CLI/SDK read sites only knew snake_case
  keys (`total_tokens` / `prompt_tokens` / etc) and silently counted Gemini
  shape (`totalTokenCount` / `promptTokenCount` / `candidatesTokenCount`)
  as zero. Extracted a shared `normalize_token_usage` helper in `models.py`
  that handles all three provider shapes, routed four read sites through
  it: `build_observability_report`, `_estimate_step_cost_usd`,
  `_print_run_summary`, inspect token aggregation, and `Run.total_tokens`.

- **No stray `RuntimeError: no running event loop` during function-step
  crashes (#12).** `_async_compat.run_coro_blocking` called `asyncio.run(coro)`
  inside the loop-detection `except` block, so coroutine exceptions chained
  to the probe RuntimeError and rendered with the misleading "During
  handling of the above exception, another exception occurred." Lifted the
  call out of the except block.

- **Workflow loader rejects `{{ ... }}` template syntax in step `inputs:` (#13).**
  Writing `topic: "{{ inputs.topic }}"` in a step input silently passed
  through as a literal string. Now caught at load time with an actionable
  `AR-WORKFLOW-VALIDATION` error pointing at the correct bare-dot-path
  form. Option (1) (unify on `{{ }}` everywhere) remains on the table for
  v0.3.

- **Function steps always see the full state snapshot (#14).** Previously
  a function received only the resolved spec when its YAML declared an
  `inputs:` block, with no `state["inputs"]` / `state["steps"]` keys —
  identical symptom to a missing input. Merge resolved inputs on top of
  the snapshot when `inputs:` is set, so both shapes coexist.
  Backward-compatible.

- **Run summary surfaces Gemini thinking tokens (dogfood paper cut).**
  Reasoning-enabled Gemini models include `thoughtsTokenCount` in
  `totalTokenCount` but not in prompt/candidates counts, so the summary
  line read `tokens: 704 (input: 200, output: 22)` with 200+22≠704.
  Render as `tokens: 704 (input: 200, output: 22, thinking: 482)` when
  the gap is non-zero. Same fix applied to `ai inspect --steps`.

## Tests

- 824 passing (+3 vs v0.2.1: helper unit test across three provider
  shapes, observability-report Gemini regression, async_compat exception
  chaining regression, plus the function snapshot-shape contract and
  workflow-loader template-syntax rejection).

## Validated end-to-end

Dogfooded against `~/Documents/agent-runtime-agents/test-agent` real
workflows on `gemini-2.5-flash`:

- `branching_triage` (function-only branching, both branches)
- `data_pipeline` (5-step function chain)
- `example.yaml` (agent + tool + function chain)
- `research.yaml` (two-agent ReAct collaboration)

None of v0.2.2's fixes regressed any existing pattern. `ai metrics`
correctly reports totals across real Gemini runs.

## Versioning

- Bumped `pyproject.toml` version from `0.2.1` to `0.2.2`.
