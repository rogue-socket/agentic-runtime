<div align="center">

<br/>

<img src="docs/banner.svg" alt="ForrestRun — deterministic agentic runtime" width="860" />

### Build AI agent workflows that are **deterministic**, **resumable**, and **observable** — by design.

<br/>

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-306998?style=for-the-badge&logo=python&logoColor=white)](#quick-start)
[![Tests](https://img.shields.io/badge/tests-448_passing-22c55e?style=for-the-badge&logo=pytest&logoColor=white)](#tests)
[![License](https://img.shields.io/badge/license-MIT-a855f7?style=for-the-badge)](#)
[![Zero deps](https://img.shields.io/badge/http_deps-zero-f59e0b?style=for-the-badge)](#providers)

<br/>

</div>

---

## The Problem

Running AI agents in production is a mess. LLM calls fail mid-workflow. State gets lost. There's no way to tell *what happened* after a run. Retrying means re-running everything from scratch.

**ForrestRun fixes all of that.**

---

## What It Does

Define your entire agent pipeline in YAML. Mix LLM agents, Python functions, and external tools. The runtime handles everything else: execution, memory, branching, retry, persistence, replay, and resume — with full state history at every step.

```yaml
workflow:
  id: research_and_act
  version: v1
steps:
  - id: research       # 🤖 LLM agent — finds key findings
    type: agent
    agent: researcher
    inputs:
      topic: inputs.topic

  - id: classify       # ⚙️  Python function — deterministic logic
    type: function
    function: triage.classify_issue
    inputs:
      findings: steps.research.findings

  - id: notify         # 🔧 Tool — external action (HTTP, shell, file)
    type: tool
    tool: tools.http
    inputs:
      url: "https://hooks.example.com/alert"
      body: steps.classify.summary
```

---

## Three Primitives, Infinite Possibilities

| Step Type | What It's For | Backed By |
|---|---|---|
| `type: agent` | LLM reasoning — summarize, plan, review, extract | Your `agents/*.yaml` |
| `type: function` | Deterministic logic — parse, classify, transform | Your `functions/*.py` |
| `type: tool` | External actions — HTTP, file I/O, shell commands | Your `tools/*.py` |

---

## Why It's Different

| Feature | What It Means For You |
|---|---|
| 🗄️ **SQLite-backed state** | Every step's input, output, and state snapshot is persisted atomically. Crash mid-run, lose nothing. |
| 🔁 **Deterministic replay** | Re-run any past run from stored state — no LLM calls, exact same output. |
| ♻️ **Resume from failure** | A step failed on iteration 5 of 7? Resume from step 5. Skip nothing. |
| 🌿 **Conditional branching** | Route runs through different paths based on runtime state — `when: state.steps.classify.severity == "critical"`. |
| 🔒 **Scoped execution** | Workflows and agents load only from their declared directories. No cross-project namespace bleed. |
| 🧠 **Native LLM history** | ReAct agents pass structured message history to every provider — no string scratchpads, real multi-turn context. |
| 🧩 **Multi-tier memory** | Working, episodic, semantic, and procedural memory layers — all pluggable. |
| 📊 **Full observability** | HTML timeline visualization, ASCII run graphs, step diff inspection, structured JSON logs. |
| 🚫 **Zero HTTP dependencies** | All LLM adapters use Python stdlib `urllib` only. No `httpx`, no `aiohttp`, no surprises. |

---

## Quick Start

```bash
# 1. Install
conda activate agent_runtime
pip install -e .

# 2. Scaffold a new project
mkdir my-agent && cd my-agent
ai quickstart          # creates workflows/, agents/, functions/, tools/, runtime.yaml

# 3. Configure your LLM provider (.env or runtime.yaml)
echo "GEMINI_API_KEY=your-key" > .env

# 4. Run
ai run example_workflow
```

> Already have a project? Just `cd` into it and run `ai run <workflow_id>`.

---

## CLI Reference

```bash
# Run
ai run example_workflow                   # run by id (latest version)
ai run example_workflow@v2               # pin to a specific version
ai run example_workflow -i topic="AI"    # pass runtime inputs
ai run example_workflow -v               # verbose structured logs

# Debug
ai inspect <run_id>                      # full run details
ai inspect <run_id> --steps             # step-by-step breakdown
ai inspect <run_id> --state-history     # state evolution across steps
ai state-diff <run_id>                  # key-path diff of state changes

# Visualize
ai visualize <run_id>                   # HTML timeline (auto-opens browser)
ai visualize <run_id> --ascii           # terminal-friendly graph

# Recover
ai resume <run_id>                      # resume a failed run from failure point
ai replay <run_id> --verify-state       # deterministic replay with state verification

# Manage
ai list                                 # list available agents
ai runs                                 # list recent runs
```

---

## LLM Providers

Configure in `runtime.yaml` — API keys resolved from environment variables or `.env`.

| Provider | Model Examples | Key |
|---|---|---|
| **OpenAI** | `gpt-4o`, `gpt-4-turbo` | `OPENAI_API_KEY` |
| **Anthropic** | `claude-3-opus`, `claude-3-5-sonnet` | `ANTHROPIC_API_KEY` |
| **Gemini** | `gemini-2.5-flash`, `gemini-1.5-pro` | `GEMINI_API_KEY` |
| **Local** | Any OpenAI-compatible server | `LOCAL_LLM_KEY` |

All adapters support structured multi-turn `history` for ReAct agents. All use stdlib `urllib` — no third-party HTTP libraries required.

---

## Docs

| What you need | Where to look |
|---|---|
| First run, zero to running | [Getting Started](docs/guide/getting-started.md) |
| Full CLI + config reference | [Usage Guide](docs/guide/usage.md) |
| Writing workflows | [Workflows](docs/guide/workflows.md) |
| Writing LLM agents | [Writing Agents](docs/guide/writing-agents.md) |
| Writing Python functions | [Writing Functions](docs/guide/writing-functions.md) |
| Writing custom tools | [Writing Tools](docs/guide/writing-tools.md) |
| System design & internals | [Architecture](docs/about/architecture.md) |
| Local docs UI with search | [docs/index.html](docs/index.html) |
| Change history | [Changelog](docs/changelog/README.md) |

---

## Tests

```bash
pytest -q    # 448 tests, all passing
```

---

<div align="center">

Built for developers who want AI agents that **run reliably in production** — not just in demos.

*ForrestRun — deterministic agentic runtime*

</div>
