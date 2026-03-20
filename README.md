<div align="center">

# agentic-runtime

**A deterministic execution runtime for AI agents.**

Define workflows and agents in YAML. Execute with full state tracking. Resume from failure. Replay any run.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](#quick-start)
[![Tests](https://img.shields.io/badge/tests-413_passing-brightgreen.svg)](#tests)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](#)

</div>

---

## What It Is

`agentic-runtime` is a YAML-driven execution runtime for AI agent workflows. You define multi-step pipelines that mix LLM agents, Python functions, and tools — and the runtime handles execution, state management, retry/backoff, conditional branching, persistence, replay, and resume.

**Three step types drive everything:**

| Step Type | Purpose | Lives In |
|-----------|---------|----------|
| `type: agent` | LLM-backed reasoning (summarize, review, plan) | `agents/` |
| `type: function` | Deterministic Python logic (parse, classify, format) | `functions/` |
| `type: tool` | External actions (HTTP, file I/O, shell) | `tools/` |

**Key capabilities:**
- SQLite-backed persistence with atomic transactions
- Deterministic replay from stored state (no re-execution)
- Resume failed runs from the exact failure point
- Conditional branching with safe expression evaluation
- Per-step retry with fixed or exponential backoff
- Multi-tier memory (working, episodic, semantic, procedural)
- Versioned prompts and agent definitions
- HTML and ASCII run visualization
- Zero third-party HTTP deps — all LLM adapters use stdlib `urllib`

## Quick Start

```bash
conda activate agent_runtime
pip install -r requirements.txt
pip install -e .

mkdir my-agent && cd my-agent
ai quickstart
```

Your agent project can live anywhere; the CLI treats the current directory as the project root.

## Docs

**Get started:**
- [docs/guide/getting-started.md](docs/guide/getting-started.md) — zero-to-first-run quickstart
- [docs/guide/manual.md](docs/guide/manual.md) — complete reference in one place
- [docs/guide/usage.md](docs/guide/usage.md) — CLI reference and scenario cookbook

**Learn the concepts:**
- [docs/guide/workflows.md](docs/guide/workflows.md) — writing workflows
- [docs/guide/writing-agents.md](docs/guide/writing-agents.md) — writing agent definitions
- [docs/guide/writing-functions.md](docs/guide/writing-functions.md) — writing function steps
- [docs/guide/writing-tools.md](docs/guide/writing-tools.md) — writing tool steps
- [docs/guide/knowledge-base.md](docs/guide/knowledge-base.md) — conceptual overview

**Understand the internals:**
- [docs/about/architecture.md](docs/about/architecture.md) — system design and execution model
- [docs/about/evolution.md](docs/about/evolution.md) — how and why the design changed
- [docs/guide/execution-walkthrough.md](docs/guide/execution-walkthrough.md) — step-by-step run trace

**Track changes:**
- [docs/changelog/CHANGELOG_2026-03-20.md](docs/changelog/CHANGELOG_2026-03-20.md) — latest changes
- [docs/index.html](docs/index.html) — local docs UI with search

## CLI At A Glance

```bash
ai quickstart                          # scaffold + configure + run
ai run workflows/example.yaml          # run a workflow by path
ai run summarizer                      # run by agent id (resolves from agents/)
ai run my_workflow@v2                   # run a specific workflow version
ai run my_workflow -i issue="bug"       # pass inputs
ai run my_workflow -v                   # verbose structured logs
ai inspect <run_id> --steps            # inspect step details
ai inspect <run_id> --state-history    # inspect state evolution
ai visualize <run_id>                  # HTML visualization (auto-opens)
ai visualize <run_id> --ascii          # terminal-friendly visualization
ai resume <run_id>                     # resume a failed run
ai replay <run_id> --verify-state      # deterministic replay with verification
ai state-diff <run_id>                 # key-path state changes
ai validate <manifest>                 # pre-flight checks
ai export <manifest>                   # bundle agent as .tar.gz
ai import <archive>                    # import agent archive
ai list                                # list agents
```

## Providers

Supports `openai`, `anthropic`, and `gemini`. API keys are resolved from environment variables (via `.env`) and provider settings live in `runtime.yaml`. All adapters use stdlib `urllib` — no third-party HTTP dependencies.

## Tests

```bash
pytest -q    # 448 tests, all passing
```
