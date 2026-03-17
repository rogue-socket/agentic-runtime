# Copilot Instructions

When assisting with this repo:

- Follow the architecture defined in .copilot/project_context.md
- Consult docs/ARCHITECTURE.md and docs/GAPS_2026-03-16.md for design context
- Prefer modifying existing modules over creating new files
- Do not introduce external dependencies without discussion — the project uses stdlib urllib for HTTP, not requests/httpx
- Respect the plugin registry pattern: handlers, tools, LLM providers, and workflows all use name→object registries with register/get APIs
- Respect the namespaced state model: all state access goes through RuntimeState with inputs.*/steps.*/runtime.* paths
- Keep handlers as plain callables (Callable[[RuntimeState], dict]) unless the contract changes
- Tools must implement the Tool protocol (name, description, input_schema, execute)
- All persistence goes through the Storage ABC — never access SQLite directly from other modules
- Use safe_eval() for any user-supplied expressions — never raw eval/exec
- Run tests with: pytest tests/ from the repo root
- Use structured logging (StructuredLogger) not print() for runtime output
- Async-first internally, sync wrappers for CLI — do not add new asyncio.run() calls in nested contexts
- Security-sensitive areas: tools/file.py path validation, agent/packaging.py archive extraction, utils.py safe_eval
