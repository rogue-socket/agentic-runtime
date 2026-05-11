<div align="center">

<br/>

<img src="documentation/banner.svg" alt="ForrestRun — deterministic agentic runtime" width="860" />

### Embeddable workflow engine for AI agents. Deterministic, resumable, zero dependencies.

<br/>

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-306998?style=for-the-badge&logo=python&logoColor=white)](#quick-start)
[![Tests](https://img.shields.io/badge/tests-797_passing-22c55e?style=for-the-badge&logo=pytest&logoColor=white)](#tests)
[![License](https://img.shields.io/badge/license-MIT-a855f7?style=for-the-badge)](#)
[![Zero deps](https://img.shields.io/badge/http_deps-zero-f59e0b?style=for-the-badge)](#llm-providers)

<br/>

</div>

---

## What is ForrestRun?

ForrestRun is a Python library for running AI agent workflows. Define your pipeline in YAML — mixing LLM agents, Python functions, and external tools — and run it with a few lines of code. Every step is persisted to SQLite, so you get replay, resume, and full state history out of the box.

```python
from forrestrun import RuntimeBuilder

with RuntimeBuilder().with_model("openai/gpt-4o").with_db_path(":memory:").build() as runtime:
    run = runtime.run("workflows/research.yaml", inputs={"topic": "AI agents"})
    print(run.outputs)          # all step outputs
    print(run.total_tokens)     # token usage across all steps
```

Or for the simplest case — one function call, no setup:

```python
from forrestrun import run_workflow

result = run_workflow("workflows/shopping.yaml", inputs={"shopping_list": "Buy a good book under 20 dollars"})
print(result.get_output("browse_and_checkout"))
```

Both `import forrestrun` and `import agent_runtime` work. No framework lock-in, no infrastructure, no dependency tree. `pip install` and go.

---

## Why ForrestRun instead of LangGraph / CrewAI?

**You want a library, not a platform.** ForrestRun is a single `pip install` with two dependencies (PyYAML, typing-extensions). No HTTP client libraries, no vector databases, no required services. It embeds into your existing Python application — FastAPI, Django, scripts, Lambda — without pulling in an ecosystem.

**You want determinism, not magic.** Every step reads from and writes to an explicit state tree. No hidden state, no implicit globals, no action-at-a-distance. Workflows are YAML files you can diff, review, and version-control like any other config.

---

## Define Workflows in YAML

Three step types — that's the whole model:

| Step Type | What It Does | Backed By |
|---|---|---|
| `type: agent` | LLM reasoning — summarize, plan, decide, extract | Your `agents/*.yaml` |
| `type: function` | Deterministic Python — parse, classify, transform | Your `functions/*.py` |
| `type: tool` | External actions — HTTP calls, shell commands, file I/O | Your `tools/*.py` |

```yaml
schema_version: v1
workflow:
  id: research_and_act
  version: v1

inputs:
  topic:
    description: What to research

steps:
  - id: research
    type: agent
    agent: researcher
    inputs:
      topic: inputs.topic

  - id: classify
    type: function
    function: triage.classify_issue
    inputs:
      findings: steps.research.findings

  - id: notify
    type: tool
    tool: tools.http
    inputs:
      url: "https://hooks.example.com/alert"
      body: steps.classify.summary
```

---

## What You Get

| Feature | How It Works |
|---|---|
| **SQLite-backed state** | Every step's input, output, and state snapshot persisted atomically. Crash mid-run, lose nothing. |
| **Deterministic replay** | Re-run any past execution from stored state. No LLM calls, exact same output. |
| **Resume from failure** | Step 5 of 7 failed? Resume from step 5 — skip nothing, re-run nothing. |
| **Conditional branching** | Route execution based on runtime state: `when: state.steps.classify.severity == "critical"` |
| **Multi-tier memory** | Working, episodic, semantic memory layers available to agents across runs. |
| **Full observability** | Structured logs, HTML timeline visualization, step-by-step state inspection. |
| **Zero HTTP dependencies** | All LLM adapters use Python stdlib `urllib`. No `httpx`, no `aiohttp`. |

---

## Quick Start

```bash
pip install forrestrun

# scaffold a new project
mkdir my-agent && cd my-agent
ai init

# run a workflow
ai run workflows/example.yaml
```

### LLM Providers

Configure in `runtime.yaml` — API keys resolved from environment or `.env`:

| Provider | Models | Key |
|---|---|---|
| **OpenAI** | `gpt-4o`, `gpt-4-turbo` | `OPENAI_API_KEY` |
| **Anthropic** | `claude-sonnet-4-20250514`, `claude-3-5-sonnet` | `ANTHROPIC_API_KEY` |
| **Gemini** | `gemini-2.5-flash`, `gemini-1.5-pro` | `GEMINI_API_KEY` |

All adapters use stdlib `urllib` and support structured multi-turn history for ReAct agents.

#### macOS SSL note

Because adapters use stdlib `urllib` (no transitive `certifi` dep), fresh macOS
Python installs can hit `SSL: CERTIFICATE_VERIFY_FAILED` on the first LLM call.
Fix with either:

```bash
# Option A — python.org installs
/Applications/Python\ 3.x/Install\ Certificates.command

# Option B — point urllib at certifi's bundle
pip install certifi
export SSL_CERT_FILE=$(python -c "import certifi; print(certifi.where())")
```

---

## CLI

ForrestRun also ships a CLI for running, inspecting, and debugging workflows:

```bash
ai run workflows/example.yaml               # run a workflow
ai run workflows/example.yaml -i topic="AI"  # pass inputs
ai inspect <run_id> --steps                  # step-by-step breakdown
ai resume <run_id>                           # resume from failure point
ai replay <run_id> --verify-state            # deterministic replay
ai visualize <run_id>                        # HTML timeline
ai runs                                      # list recent runs
```

---

## Project Structure

When you run `ai init`, ForrestRun scaffolds:

```
my-agent/
  agents/          # LLM agent definitions (YAML)
  functions/       # deterministic Python functions
  tools/           # custom tool implementations
  workflows/       # workflow definitions (YAML)
  runtime.yaml     # config (provider, model, limits)
  .env             # API keys
```

---

## Docs

| Topic | Link |
|---|---|
| Getting started | [documentation/guide/getting-started.md](documentation/guide/getting-started.md) |
| Writing workflows | [documentation/guide/workflows.md](documentation/guide/workflows.md) |
| Writing agents | [documentation/guide/writing-agents.md](documentation/guide/writing-agents.md) |
| Writing functions | [documentation/guide/writing-functions.md](documentation/guide/writing-functions.md) |
| Writing tools | [documentation/guide/writing-tools.md](documentation/guide/writing-tools.md) |
| Architecture | [documentation/about/architecture.md](documentation/about/architecture.md) |
| Full CLI reference | [documentation/guide/cli-reference.md](documentation/guide/cli-reference.md) |

---

## Tests

```bash
pytest -q    # 797 tests
```

---

<div align="center">

*ForrestRun — the workflow engine that stays out of your way.*

</div>
