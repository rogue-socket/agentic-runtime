# Changelog — 2026-03-23

## Orchestration & Agent Runtime

- **ReAct Context Amnesia Fix (proper native history)**:
  Resolved a critical bug where ReAct loop iterations failed to inject prior tool outputs
  and observations back into the LLM context. The fix refactors the `LLMAdapter` protocol
  and all downstream providers (`OpenAIAdapter`, `AnthropicAdapter`, `GeminiAdapter`) to
  natively accept and process a structured `history: List[Dict[str, str]]` array.
  `LLMClient.call` also gains a new `history` keyword argument. The `ReActStrategy` now
  rebuilds the structured message history from `AgentTurn` objects before each iteration,
  giving the model a full rolling view of its own prior reasoning and tool observations as
  genuine chat messages — not string concatenation into the prompt.

- **Scoped Globbing for Runtime Loaders (duplicate-version prevention)**:
  Fixed an environment-bleed bug that raised `Duplicate workflow version` errors when the
  CLI was invoked from a parent directory containing multiple agent project subdirectories.
  `WorkflowRegistry.from_directory` changed from `rglob` to `glob` (flat scan) and
  `AgentRegistry.from_directory` dropped the `recursive=True` flag. Both registries now
  load only definitions in the explicitly declared directory root, preventing cross-project
  namespace collisions.

- **Step Output Dictionary Passing (dot-path relaxation)**:
  Removed the artificial 3-segment minimum enforcement on `steps.*` input paths inside
  `workflow.py`. Paths like `steps.pay_and_confirm` (2 segments) are now valid and resolve
  to the entire output dictionary of the referenced step. This was previously blocked by a
  validation error (`Invalid step input path`) that prevented whole dicts from being passed
  between steps. The underlying `utils.resolve_path` already handles arbitrary depth lookups
  correctly — the restriction in the validator was the only missing piece.

## Built-in Tools

- **`tools.echo` — accepts any JSON-serializable value**:
  The echo tool previously declared `message` as `type: string` in its input schema,
  causing `validate_input` to throw `ValueError: Field 'message' must be string` when a
  dict or list was passed (e.g. `steps.pay_and_confirm` resolving to the full agent output
  dict). The schema property is now type-agnostic (`{}`), and `execute` coerces non-string
  values to a pretty-printed JSON string (`json.dumps(indent=2)`) before returning. String
  values are passed through unchanged.

## Documentation

- Updated `docs/guide/workflows.md`: corrected the "How Data Moves" section — removed the
  outdated 3-segment restriction note and replaced it with accurate guidance that whole step
  output dicts may now be referenced.
- Updated `docs/guide/tools.md` (if present) or inline above: documented the echo tool's
  new any-type `message` contract.
