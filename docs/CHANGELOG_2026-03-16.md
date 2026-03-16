# Changelog — 2026-03-16

## Added
- LLM client and OpenAI adapter with structured logging hooks and normalized responses.
- Built-in `llm` handler with state-based prompt templating.
- Workflow parsing support for `handler: llm` step fields (`model`, `prompt`, `system`, and related params).
- `{{ path }}` state template rendering helper.

## Changed
- Executor now supports async-native execution with sync wrappers that refuse to run inside an active event loop.
- Tool execution path is async to avoid `asyncio.run()` in embedded contexts.

## Tests
- Added coverage for async run execution and loop-guard behavior.
