# Project Context

## Project Overview
agentic-runtime — a deterministic, local-first execution runtime for LLM-powered AI agent workflows. Not a framework or library — the execution substrate agents run on. Analogous to a JVM for AI pipelines. Workflows are defined in YAML, executed step-by-step with full state tracking, and persisted to SQLite. Supports failure recovery (resume), deterministic replay, conditional branching, and portable agent packaging.

## Tech Stack
- **Language:** Python 3.10+ (async-first internals, sync CLI wrappers)
- **Persistence:** SQLite (runs, steps, state_versions tables)
- **Workflow format:** YAML
- **HTTP:** stdlib urllib (OpenAI/Anthropic adapters — no SDK dependencies)
- **CLI:** argparse
- **Dependencies:** PyYAML, typing-extensions (minimal footprint)
- **Testing:** pytest
- **No packaging yet** — no pyproject.toml (TODO)

## Architecture Overview
```
CLI (cli.py)
  → Config (config.py) + Registry bootstrap
  → Workflow parser (workflow.py) — YAML → StepDefinition[]
  → Executor (core.py) — step loop with retry/branch/resume
      → Handlers (steps.py) — model-type steps (Callable[[RuntimeState], dict])
      → LLM Client (llm/) — llm-type steps via provider adapters
      → Tools (tools/) — tool-type steps via Tool protocol
      → Memory (memory/) — 4-tier hydrate/persist around execution
  → Storage (storage/sqlite.py) — runs, steps, state_versions tables
```

State is namespaced: `{ inputs: {}, steps: {}, runtime: {} }` with deep-copy snapshots at every step boundary.

## Key Modules / Major Directories
| Directory / File | Purpose |
|------------------|---------|
| `src/agent_runtime/core.py` | Executor engine, Run/StepExecution datamodels, retry/branch loop |
| `src/agent_runtime/workflow.py` | YAML parser, step validation, handler resolution, workflow hashing |
| `src/agent_runtime/state.py` | RuntimeState — dot-path access, snapshots, diffing |
| `src/agent_runtime/steps.py` | StepHandlerRegistry + 5 built-in scaffold handlers |
| `src/agent_runtime/cli.py` | `ai` CLI — init, run, inspect, resume, replay, visualize, etc. |
| `src/agent_runtime/config.py` | RuntimeConfig from runtime.yaml with CLI override precedence |
| `src/agent_runtime/errors.py` | 10-type exception hierarchy under RuntimeErrorBase |
| `src/agent_runtime/utils.py` | safe_eval, template rendering, hashing, path resolution |
| `src/agent_runtime/llm/` | LLM registry, OpenAI/Anthropic adapters, client facade, llm handler |
| `src/agent_runtime/tools/` | Tool protocol, registry, discovery, validation, 4 built-in tools |
| `src/agent_runtime/memory/` | MemoryTier protocol, MemoryManager, 4 tiers (episodic implemented) |
| `src/agent_runtime/storage/` | Storage ABC + SQLiteStorage |
| `src/agent_runtime/agent/` | AgentManifest, export/import as .tar.gz archives |
| `src/agent_runtime/visualization/` | Graph/timeline builders, ASCII + HTML renderers |
| `src/agent_runtime/resume.py` | Resume-point resolution for failed runs |
| `src/agent_runtime/replay.py` | Deterministic replay from stored step history |
| `workflows/` | Example and sample YAML workflows |
| `tests/` | ~19 pytest test files |
| `docs/` | Architecture, status, gap analysis, changelogs |

## Development Patterns
- **Plugin registries** — StepHandlerRegistry, ToolRegistry, LLMRegistry, WorkflowRegistry (name→object register/get maps)
- **Protocol-based extension** — Tool, MemoryTier, LLMAdapter, Storage (structural typing via Python protocols/ABCs)
- **Auto-discovery** — handlers from `handlers/`, tools from `tools/` directory scanning at startup
- **Workflow content hashing** — SHA-256 of YAML for resume safety (blocks resume if workflow changed)
- **Safe expression eval** — AST-validated branch conditions restricted to `state` + `len`
- **Output contracts** — declared step outputs enforced at runtime (missing/undeclared keys fail)
- **Namespaced state** — prevents cross-step key collisions
- **Async-first internals** with sync wrappers via `asyncio.run()` for CLI

## Testing Strategy
- **Framework:** pytest
- **Isolation:** temp SQLite databases per test, in-memory memory managers, minimal registries
- **Coverage areas:** ~19 test files — core execution, branching, resume, replay, tools, storage roundtrip, visualization, LLM registry, state management, step contracts, workflow versioning
- **Pattern:** each test builds a minimal workflow YAML string, registers only needed handlers/tools, runs through Executor, asserts on Run/StepExecution/state

## Build & Run Instructions
```bash
# Install dependencies
pip install -r requirements.txt

# Run tests
pytest tests/

# CLI usage (from repo root)
python -m agent_runtime.cli init          # scaffold project
python -m agent_runtime.cli run <ref>     # execute workflow
python -m agent_runtime.cli inspect <id>  # inspect run
python -m agent_runtime.cli resume <id>   # resume failed run
python -m agent_runtime.cli replay <id>   # deterministic replay
```

## Subsystem Status (as of 2026-03-17)
| Subsystem | Status |
|-----------|--------|
| Core executor | Implemented |
| Workflow parser | Implemented |
| State manager | Implemented |
| Storage (SQLite) | Implemented |
| CLI | Implemented |
| Resume / Replay | Implemented |
| Visualization | Implemented |
| Agent manifest & packaging | Implemented |
| LLM registry + adapters + handler | Implemented |
| Tools (echo, http, file, shell) | Implemented |
| Episodic memory | Implemented (SQLite-backed) |
| Working / Semantic / Procedural memory | Scaffolding only |
