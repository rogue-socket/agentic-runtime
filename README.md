<div align="center">

# agentic-runtime

**A deterministic execution runtime for AI agents.**

Define agents in YAML. Run them with full state tracking. Resume from failure. Replay any historical run. Package and ship agents as portable archives.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](#setup)
[![Tests](https://img.shields.io/badge/tests-15_suites-passing.svg)](#tests)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](#)

</div>

---

## Why this exists

Agent systems break in predictable ways as they scale:

| Problem | What happens |
|---|---|
| **No execution trace** | "What did the agent actually do?" — nobody knows |
| **Uncontrolled state** | Multiple steps mutate a shared dict, ownership is unclear |
| **Transient failures** | One API timeout kills a 10-step run — start over from scratch |
| **Black-box branching** | Agent took path A instead of B — no way to see why |
| **No postmortems** | Can't reproduce what happened yesterday |
| **Ad-hoc LLM management** | API keys scattered, no unified provider config |

`agentic-runtime` is built to solve these. It's not a framework you import — it's the execution substrate agents run **on**.

---

## How it works

```
                          ┌─────────────────────────────────────────┐
   agent.yaml             │            agentic-runtime              │
   ┌──────────┐           │                                         │
   │ agent:   │           │  ┌──────────┐    ┌───────────────────┐  │
   │   id     │──────────▶│  │ Executor │───▶│  SQLite Storage   │  │
   │   version│           │  └────┬─────┘    │  - runs           │  │
   │ workflow │           │       │          │  - steps          │  │
   │ handlers │           │  ┌────▼─────┐    │  - state_versions │  │
   │ tools    │           │  │  Steps   │    └───────────────────┘  │
   │ providers│           │  │ ┌──────┐ │    ┌───────────────────┐  │
   └──────────┘           │  │ │model │ │───▶│  Handler Registry │  │
                          │  │ ├──────┤ │    └───────────────────┘  │
   workflow.yaml          │  │ │ tool │ │    ┌───────────────────┐  │
   ┌──────────┐           │  │ └──────┘ │───▶│   Tool Registry   │  │
   │ steps:   │──────────▶│  └──────────┘    └───────────────────┘  │
   │  - model │           │       │          ┌───────────────────┐  │
   │  - tool  │           │       └─────────▶│  LLM Registry     │  │
   │  - branch│           │                  │  (multi-provider)  │  │
   └──────────┘           │                  └───────────────────┘  │
                          └─────────────────────────────────────────┘
                                     │
                          ┌──────────▼──────────┐
                          │   Durable Run Record │
                          │   - state_before/after per step
                          │   - attempt_count, errors
                          │   - workflow_hash (integrity lock)
                          │   - full state evolution
                          └─────────────────────┘
```

**Execution contract:**

1. Load workflow definition (from file, registry, or agent manifest)
2. Create run record + initial state snapshot
3. Execute steps sequentially — retry, branch, track state
4. Persist every step record and state version to SQLite
5. Terminal status: `COMPLETED` / `FAILED` / `COMPLETED_WITH_ERRORS`

Every run is inspectable, resumable, and replayable after the fact.

---

## Quickstart

<!-- TODO(packaging): Replace PYTHONPATH hack with `pip install agentic-runtime`
     once pyproject.toml and PyPI publishing are set up. The install step
     should be: pip install agentic-runtime && ai init && ai run example_agent@v1 -->
<!-- TODO(ux): Add a "5-minute getting started" section aimed at a solo dev
     building their first agent. Walk through: install, init, set OPENAI_API_KEY,
     run a workflow that calls a real LLM, inspect the result. -->

```bash
# Install
pip install -r requirements.txt

# Scaffold a project
PYTHONPATH=src python -m agent_runtime.cli init

# Run the example agent
PYTHONPATH=src python -m agent_runtime.cli run example_agent@v1

# See what happened
PYTHONPATH=src python -m agent_runtime.cli inspect <run_id> --steps
```

This creates:

```
your-project/
├── agents/
│   └── example_agent.yaml     # agent manifest (the portable unit)
├── workflows/
│   └── example.yaml           # workflow definition
├── handlers/
│   └── example_handler.py     # model step handler
├── tools/
│   └── example_tool.py        # tool implementation
└── runtime.yaml               # runtime configuration (LLM providers, paths, logging)
```

---

## Key concepts

### Agent manifest

An `agent.yaml` is the portable unit of the runtime. It declares everything an agent needs to run:

```yaml
agent:
  id: triage_agent
  version: v2
  description: "Triages incoming issues by severity"

workflow: workflows/triage.yaml

handlers:
  - handlers/classify.py
  - handlers/summarize.py

tools:
  - tools/github.py

providers:
  - name: openai
    models: [gpt-4]

env:
  - GITHUB_TOKEN

defaults:
  issue: "unspecified"
```

Agents can be validated, exported as `.tar.gz` archives, and imported into other projects.

### Workflows

Ordered YAML steps with identity, versioning, retry policies, and conditional branching:

```yaml
workflow:
  id: issue_triage
  version: v1

inputs:
  issue:
    description: The issue text to analyze
    default: "Login API fails for invalid token"

on_error: fail_fast

steps:
  - id: summarize
    type: model
    handler: generate_summary
    inputs:
      issue: inputs.issue
    outputs: [summary]
    retry:
      attempts: 3
      backoff: exponential
      initial_delay: 1

  - id: classify
    type: model
    handler: classify_severity
    inputs:
      summary: steps.summarize.summary
    outputs: [severity]

  - id: route
    type: tool
    tool: tools.echo
    inputs:
      message: steps.classify.severity
    next:
      - when: state.steps.classify.severity == "critical"
        goto: escalate
      - default: log_result
```

### Namespaced state

State is structured — not a free-form dict:

```json
{
  "inputs":  { },          // immutable run input
  "steps":   { },          // per-step outputs (steps.<id>.*)
  "runtime": { }           // runtime metadata
}
```

This prevents cross-step key collisions, preserves output ownership, and makes debugging tractable.

### Step contracts

Declare what each step reads and writes:

```yaml
- id: summarize
  inputs: [issue]           # reads from state
  outputs: [summary]        # writes to state
```

The runtime enforces these at load time (future-read detection, output collision) and at execution time (output shape validation).

---

## CLI reference

### Agent lifecycle

```bash
ai validate agents/my_agent.yaml          # pre-flight checks (files, providers, env vars)
ai export agents/my_agent.yaml -o out.tar.gz  # package as portable archive
ai import agent_archive.tar.gz             # extract into project
ai list                                    # list all agents
```

### Run

```bash
ai run triage_agent@v2                     # run by agent id (resolves from agents/)
ai run workflows/triage.yaml              # run by file path
ai run code_review_agent                   # run latest version from workflow registry
ai run triage_agent -i issue="crash on login"  # override default inputs
```

### Inspect

```bash
ai inspect <run_id>                        # run summary
ai inspect <run_id> --steps                # step-by-step detail
ai inspect <run_id> --state-history        # full state evolution
```

### Resume from failure

```bash
ai resume <run_id>                         # continue from first failed step
ai resume <run_id> --workflow triage.yaml  # validate against specific workflow file
```

Resume enforces a **workflow integrity lock**: if the YAML has been modified since the original run, resume is blocked. This prevents resuming against a different workflow than the one that started the run.

### Replay (read-only simulation)

```bash
ai replay <run_id>                         # replay from persisted history
ai replay <run_id> --verify-state          # check state consistency
ai replay <run_id> --step-by-step          # pause between steps
ai replay <run_id> --until classify        # replay up to a specific step
```

No handlers, tools, or APIs are called during replay. It reconstructs the run from stored data.

### Visualize

```bash
ai visualize <run_id> --ascii              # terminal-friendly view
ai visualize <run_id> --timeline           # state change timeline
ai visualize <run_id>                      # HTML report (auto-opens browser)
```

### Debug state changes

```bash
ai state-diff <run_id>                     # all steps
ai state-diff <run_id> --step classify     # one step
```

```
Step: classify
+ steps.classify.severity = critical
+ steps.classify.confidence = 0.94
```

---

## Architecture

### Execution engine

The `Executor` runs steps using a pointer model (not list iteration), which supports both linear flow and conditional branching with the same mechanism.

For each step:
1. Snapshot `state_before`
2. Build step input from state path mapping
3. Execute with retry policy (fixed or exponential backoff)
4. Validate output against declared contract
5. Write output to `steps.<step_id>` namespace
6. Snapshot `state_after`
7. Persist `StepExecution` record + new state version
8. Resolve next step (branch rules or sequential fallback)

### Handler system

Handlers are Python functions for `model` steps:

```python
def classify_severity(state: RuntimeState) -> dict:
    issue = state.get("issue")
    # your logic here
    return {"severity": "critical", "confidence": 0.94}
```

Handlers are auto-discovered from the `handlers/` directory. Two conventions:
- **Zero-config:** Every public function is registered by name
- **Explicit:** Define `__handlers__ = {"name": fn}` for full control

### Tool system

Tools are structured objects for `tool` steps with schema validation, timeouts, retries, and runtime context injection:

```python
class GitHubTool:
    name = "tools.github"
    description = "Fetches issue details from GitHub"
    input_schema = {
        "type": "object",
        "properties": {"repo": {"type": "string"}, "issue_number": {"type": "integer"}}
    }
    timeout = 30.0
    retries = 2

    async def execute(self, input, context: RuntimeContext) -> ToolResult:
        # ...
        return ToolResult(success=True, output={"title": "...", "body": "..."})
```

Tools are auto-discovered from the `tools/` directory.

**Built-in tools** (always available):

| Tool | Name | What it does |
|---|---|---|
| `EchoTool` | `tools.echo` | Returns input message (testing/examples) |
| `HttpTool` | `tools.http` | HTTP/HTTPS requests with scheme validation (GET, POST, PUT, PATCH, DELETE) |
| `FileTool` | `tools.file` | Read/write/append/list files, sandboxed to project root |
| `ShellTool` | `tools.shell` | Execute shell commands with timeout and output capture |

### LLM provider registry

Multi-provider management with environment-based credential resolution:

```yaml
# runtime.yaml
llm:
  providers:
    openai:
      api_key_env: OPENAI_API_KEY
      models:
        gpt-4:
          temperature: 0.2
          max_tokens: 4096
    anthropic:
      api_key_env: ANTHROPIC_API_KEY
      models:
        claude-3-opus:
          temperature: 0.3
    gemini:
      api_key_env: GEMINI_API_KEY
      models:
        gemini-2.5-flash:
          temperature: 0.2
          max_tokens: 8192
```

API keys are **never stored on disk** — resolved from environment variables at call time.

### Persistence

SQLite with three tables:

| Table | Purpose |
|---|---|
| `runs` | Run metadata, status, workflow snapshot, hashes |
| `steps` | Per-step execution records with full state snapshots |
| `state_versions` | Ordered state evolution for replay and debugging |

### Error hierarchy

All exceptions inherit from `RuntimeErrorBase`:

| Exception | When |
|---|---|
| `WorkflowValidationError` | Invalid YAML structure |
| `StepExecutionError` | Handler/tool failure |
| `ToolNotFoundError` | Unknown tool reference |
| `HandlerNotFoundError` | Unknown handler reference |
| `BranchResolutionError` | No matching branch rule |
| `WorkflowIntegrityError` | Workflow modified after run (blocks resume) |
| `AgentValidationError` | Invalid agent manifest |
| `RunNotFoundError` | Run ID not in storage |
| `ReplayDataMissingError` | Incomplete data for replay |
| `ReplayMismatchError` | Replay state diverges from recorded |

---

## Sample workflows

Ready-to-run examples in `workflows/samples/`:

| Workflow | Demonstrates |
|---|---|
| `01_linear_issue_summary.yaml` | Basic linear execution |
| `02_retry_and_backoff.yaml` | Retry with exponential backoff |
| `03_branching_triage.yaml` | Conditional branching by severity |
| `04_fail_and_resume.yaml` | Deliberate failure + resume recovery |
| `06_gemini_call.yaml` | Gemini-backed LLM call |
| `versioning/code_review_agent_v1.yaml` | Workflow versioning (v1) |
| `versioning/code_review_agent_v2.yaml` | Workflow versioning (v2) |

```bash
# Run a sample
PYTHONPATH=src python -m agent_runtime.cli run workflows/samples/03_branching_triage.yaml -i issue="critical bug"

# Inspect the branch path
PYTHONPATH=src python -m agent_runtime.cli inspect <run_id> --steps
```

---

## Project structure

```
src/agent_runtime/
├── cli.py                  # CLI command surface (11 commands)
├── core.py                 # Executor engine, Run/Step datamodels
├── config.py               # runtime.yaml loader with CLI overrides
├── errors.py               # Exception hierarchy (10 types)
├── state.py                # RuntimeState — namespaced state manager
├── steps.py                # Handler registry + built-in handlers
├── workflow.py             # YAML workflow parser and validator
├── workflow_registry.py    # Version-aware workflow resolution
├── handler_discovery.py    # Auto-discovery from handlers/ directory
├── resume.py               # Resume point determination
├── replay.py               # Deterministic replay engine
├── logging.py              # Structured JSON logger
├── utils.py                # Hashing, path resolution, safe_eval
├── agent/                  # Agent manifest system
│   ├── manifest.py         #   AgentManifest, loader, validator
│   └── packaging.py        #   export/import as .tar.gz
├── llm/                    # LLM subsystem
│   ├── registry.py         #   LLMProvider, ModelConfig, LLMRegistry
│   ├── client.py           #   LLMClient — routes calls through adapters
│   ├── adapters.py         #   OpenAIAdapter, AnthropicAdapter, GeminiAdapter
│   ├── handler.py          #   Built-in `llm` handler for workflow steps
│   └── types.py            #   LLMResponse dataclass
├── memory/                 # Memory tier subsystem
│   ├── base.py             #   MemoryTier protocol, MemoryManager
│   ├── working.py          #   WorkingMemory (scaffolding)
│   ├── episodic.py         #   EpisodicMemory (SQLite-backed)
│   ├── semantic.py         #   SemanticMemory (scaffolding)
│   └── procedural.py       #   ProceduralMemory (scaffolding)
├── storage/                # Persistence layer
│   ├── base.py             #   Abstract Storage interface
│   └── sqlite.py           #   SQLiteStorage implementation
├── tools/                  # Tool subsystem
│   ├── base.py             #   Tool protocol, ToolResult, RuntimeContext
│   ├── registry.py         #   ToolRegistry
│   ├── discovery.py        #   Auto-discovery from tools/ directory
│   ├── echo.py             #   Built-in EchoTool
│   ├── http.py             #   Built-in HttpTool
│   ├── file.py             #   Built-in FileTool
│   ├── shell.py            #   Built-in ShellTool
│   └── validation.py       #   JSON Schema input validation
└── visualization/          # Run visualization
    ├── run_loader.py       #   Load run data for rendering
    ├── graph_builder.py    #   Execution graph construction
    ├── timeline_builder.py #   State delta timeline
    ├── ascii_renderer.py   #   Terminal renderer
    └── html_renderer.py    #   HTML report renderer
```

---

## Tests

18 test suites covering the full runtime surface:

```bash
PYTHONPATH=src pytest tests/ -v
```

| Suite | Coverage |
|---|---|
| `test_runtime.py` | Core executor lifecycle |
| `test_branching.py` | Conditional branch resolution |
| `test_branch_resume.py` | Resume from branched paths |
| `test_resume.py` | Resume validation and semantics |
| `test_retry_policy.py` | Retry/backoff behavior |
| `test_replay.py` | Deterministic replay engine |
| `test_state_manager.py` | RuntimeState operations |
| `test_state_diff.py` | State diff computation |
| `test_state_history.py` | State evolution tracking |
| `test_step_contracts.py` | Input/output contract enforcement |
| `test_visualization.py` | Graph/timeline builders, renderers |
| `test_workflow_versioning.py` | Workflow registry + version resolution |
| `test_workflow_lock.py` | Workflow integrity hash lock |
| `test_llm_registry.py` | LLM provider registry |
| `test_agent_manifest.py` | Agent manifest: load, validate, export, import |
| `test_anthropic_adapter.py` | Anthropic adapter + client routing |
| `test_gemini_adapter.py` | Gemini adapter + client routing |
| `test_builtin_tools.py` | HTTP, File, Shell tools |
| `test_episodic_memory.py` | SQLite-backed episodic memory |

---

## Design decisions

| Decision | Rationale |
|---|---|
| **Step pointer, not list iteration** | Same model supports linear flow, branching, and resume without special cases |
| **Namespaced state** (`inputs`/`steps`/`runtime`) | Prevents key collisions, makes ownership explicit, enables safe contracts |
| **Workflow hash lock on resume** | Prevents silent behavior changes when resuming against modified YAML |
| **Replay is read-only simulation** | Separates "what happened" from "what would happen" — no side effects |
| **Tools are objects, handlers are functions** | Tools need schema/timeout/retry metadata; handlers are pure logic |
| **Auto-discovery for handlers and tools** | Zero-config default, explicit `__handlers__` dict for control |
| **Credentials from env vars only** | API keys never touch disk or YAML — resolved at call time |
| **Agent manifest as portable unit** | `agent.yaml` + export/import = agents are shippable artifacts |

---

## Documentation

| Document | Purpose |
|---|---|
| `docs/ARCHITECTURE.md` | Full architectural specification (20 sections) |
| `docs/EXECUTION_WALKTHROUGH.md` | Step-by-step execution trace walkthrough |
| `docs/USAGE.md` | Detailed usage guide |
| `docs/GAPS_2026-03-17.md` | Known gaps and roadmap priorities |
| `docs/STATUS_2026-03-17.md` | Current status of every subsystem |

---

## Setup

### Requirements

- Python 3.10+
- Dependencies: `pip install -r requirements.txt`

### Environment

```bash
conda create -n agent_runtime python=3.10
conda activate agent_runtime
pip install -r requirements.txt
```

### Initialize a project

```bash
PYTHONPATH=src python -m agent_runtime.cli init --path my-agents
cd my-agents
```

### Configure LLM providers

Use `ai setup` to configure providers, or edit `runtime.yaml` and set environment variables:

```bash
ai setup --provider gemini

export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
export GEMINI_API_KEY="..."
```
