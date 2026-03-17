<div align="center">

# agentic-runtime

**A deterministic execution runtime for AI agents.**

Define agents in YAML. Run them with full state tracking. Resume from failure. Replay any historical run.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](#quick-start-new-agent)
[![Tests](https://img.shields.io/badge/tests-15_suites-passing.svg)](#tests)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](#)

</div>

---

## What it is

`agentic-runtime` is a runtime for deterministic agent execution. It focuses on durable run records, explicit state ownership, and reproducible replays across providers.

## Quick Start (New Agent)

```bash
conda activate agent_runtime
pip install -r requirements.txt
pip install -e .

mkdir my-agent
cd my-agent

ai
ai run my_agent@v1
```

Your agent project can live anywhere; the CLI treats the current directory as the project root.

## Docs

- `docs/USAGE.md` — CLI reference, workflows, inspect/resume/replay
- `docs/ONBOARDING_WALKTHROUGH.md` — guided setup flow and scripted walkthrough
- `docs/ARCHITECTURE.md` — system design
- `docs/EXECUTION_WALKTHROUGH.md` — run/resume/replay trace
- `docs/CHANGELOG_2026-03-18.md` — recent changes

## CLI at a glance

```bash
ai run my_agent@v1
ai inspect <run_id> --steps
ai visualize <run_id>
ai resume <run_id>
```

## Providers

Supports `openai`, `anthropic`, `gemini`, and `local`. API keys are resolved from environment variables (typically via `.env`) and provider settings live in `runtime.yaml`.

## Tests

```bash
pytest -q
```
