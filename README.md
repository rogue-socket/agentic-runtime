# agentic-runtime

A runtime for AI agents.

Load agents, export agents, run agents — with deterministic execution, full state tracking, and failure recovery built in.  This is not a framework or a library you call into.  It is the execution substrate your agents run *on*.

## What problem this runtime solves

When agent workflows scale, teams usually hit the same issues:

- no reproducible execution trace
- state mutations from many places with unclear ownership
- transient failures kill the whole run with no clean continuation
- branching behavior is hard to inspect and verify
- impossible to debug "what happened" after the fact
- managing multiple LLM providers and API keys is ad-hoc

`agentic-runtime` solves that with first-class run execution semantics:

- structured state (`inputs`, `steps`, `runtime`)
- per-step execution records (`state_before`, `state_after`, `attempt_count`, errors)
- retry policy at step level
- deterministic resume from failure with workflow integrity lock
- deterministic replay from persisted history (read-only simulation)
- LLM provider registry with environment-based credential management

## Runtime capabilities

- **Agent manifest system** (`agent.yaml`) — portable agent packaging with validate / export / import
- `Run` lifecycle with durable records in SQLite
- Step execution with retries/backoff
- Conditional branching (`next` with `when` + `default`)
- First-class tool interface (`Tool`, `ToolResult`, `RuntimeContext`)
- State manager abstraction (`RuntimeState`) with namespaced writes
- LLM provider registry (`LLMRegistry`) — manage multiple providers, models, and API keys
- Workflow integrity lock — resume is blocked if workflow YAML changes after a run
- Inspect modes:
  - summary
  - step-centric (`--steps`)
  - state timeline (`--state-history`)
- Replay subsystem (`ai replay`) with optional state verification
- Run visualization (`ai visualize`) with ASCII, HTML, and timeline modes
- Workflow hash + input hash for reproducibility checks
- Workflow versioning (`workflow_id`, `workflow_version`, `workflow_hash`)

## Setup

### Environment
- Conda env name: `agent_runtime`

### Install

```bash
pip install -r requirements.txt
```

### Initialize scaffold

```bash
PYTHONPATH=src ./ai init
```

Creates a project structure:

```
├── workflows/
│   └── example.yaml           # example workflow definition
├── handlers/
│   └── example_handler.py     # example model step handler
├── tools/
│   └── example_tool.py        # example tool implementation
├── agents/
│   └── example_agent.yaml     # example agent manifest
└── runtime.yaml               # runtime configuration
```

## Core commands

### Agent commands

```bash
# Validate an agent manifest (pre-flight: files, providers, env vars)
PYTHONPATH=src ./ai validate agents/my_agent.yaml

# Export an agent as a portable archive
PYTHONPATH=src ./ai export agents/my_agent.yaml -o my_agent_v1.tar.gz

# Import an agent archive into the project
PYTHONPATH=src ./ai import my_agent_v1.tar.gz

# List all agents in agents/ directory
PYTHONPATH=src ./ai list
```

### Run

```bash
# Run by agent id (resolves from agents/ directory, uses manifest defaults)
PYTHONPATH=src ./ai run example_agent@v1

# Run by workflow path (classic mode, no manifest)
PYTHONPATH=src ./ai run workflows/example.yaml
PYTHONPATH=src ./ai run example_workflow
PYTHONPATH=src ./ai run code_review_agent@v2
```

Workflows with declared inputs use defaults when no `-i` flag is given.
To override:

```bash
PYTHONPATH=src ./ai run workflows/example.yaml -i issue="Login API fails for invalid token"
PYTHONPATH=src ./ai run code_review_agent@v2 -i issue="Custom issue text"
```

### Inspect

```bash
PYTHONPATH=src ./ai inspect <run_id>
PYTHONPATH=src ./ai inspect <run_id> --steps
PYTHONPATH=src ./ai inspect <run_id> --state-history
```

### Resume failed run

```bash
PYTHONPATH=src ./ai resume <run_id>
```

### Replay deterministically (no tool/model calls)

```bash
PYTHONPATH=src ./ai replay <run_id>
PYTHONPATH=src ./ai replay <run_id> --verify-state
PYTHONPATH=src ./ai replay <run_id> --until <step_id>
PYTHONPATH=src ./ai replay <run_id> --step-by-step
```

### Visualize runs

```bash
PYTHONPATH=src ./ai visualize <run_id> --ascii
PYTHONPATH=src ./ai visualize <run_id> --timeline
PYTHONPATH=src ./ai visualize <run_id>        # default HTML at .runs/<run_id>/visualization.html (auto-opens browser)
PYTHONPATH=src ./ai visualize <run_id> --html # generate HTML without auto-opening browser
```

### State diff debugging

When you need to know exactly what changed in state:

```bash
PYTHONPATH=src ./ai state-diff <run_id>
PYTHONPATH=src ./ai state-diff <run_id> --step <step_id>
```

Example output style:

```text
Step: plan
+ steps.plan.tasks = ['t1', 't2']
+ steps.plan.priority = high
- steps.plan.draft_message (was hello)
```

## Sample workflows (ready to run)

Location: `workflows/samples/`

- `01_linear_issue_summary.yaml`
- `02_retry_and_backoff.yaml`
- `03_branching_triage.yaml`
- `04_fail_and_resume.yaml`
- `versioning/code_review_agent_v1.yaml`
- `versioning/code_review_agent_v2.yaml`

Run any sample:

```bash
PYTHONPATH=src ./ai run workflows/samples/01_linear_issue_summary.yaml
```

Override the default input:

```bash
PYTHONPATH=src ./ai run workflows/samples/01_linear_issue_summary.yaml -i issue="Custom text"
```

## How teams use this runtime in practice

### 1) Incident triage with branch visibility

Use case:
- Route issue categories through different execution paths.

Workflow:
- `workflows/samples/03_branching_triage.yaml`

Run:

```bash
PYTHONPATH=src ./ai run workflows/samples/03_branching_triage.yaml -i issue="bug"
```

Why this helps:
- `ai inspect` shows actual branch path taken in execution order.
- You can verify branch decisions from persisted state.

### 2) Stabilize flaky external interactions

Use case:
- A model/tool call fails transiently (timeouts, throttling).

Workflow:
- `workflows/samples/02_retry_and_backoff.yaml`

Run:

```bash
PYTHONPATH=src ./ai run workflows/samples/02_retry_and_backoff.yaml -i issue="Login API fails for invalid token"
```

Why this helps:
- Retry behavior is explicit in YAML.
- `attempt_count` and `last_error` show exactly what happened.

### 3) Recover failed runs without restarting

Use case:
- Mid-run failure after successful earlier steps.

Workflow:
- `workflows/samples/04_fail_and_resume.yaml`

Run + inspect + resume:

```bash
PYTHONPATH=src ./ai run workflows/samples/04_fail_and_resume.yaml -i issue="Login API fails"
PYTHONPATH=src ./ai inspect <run_id> --steps
PYTHONPATH=src ./ai resume <run_id>
```

Why this helps:
- Completed steps are not re-executed.
- Resume continues from the first non-completed step deterministically.

### 4) Deterministic debugging for postmortems

Use case:
- You need to reproduce a historical run exactly for analysis.

Replay:

```bash
PYTHONPATH=src ./ai replay <run_id> --verify-state --step-by-step
```

Why this helps:
- Replay injects recorded outputs/states.
- No external systems are invoked.
- You can audit state transitions step-by-step.

## Workflow authoring model

A workflow is ordered YAML steps with first-class identity and version metadata.

Minimal example:

```yaml
workflow:
  id: example_workflow
  version: v1
on_error: fail_fast
steps:
  - id: generate_summary
    type: model
    handler: generate_summary
    inputs:
      issue: inputs.issue

  - id: echo_tool
    type: tool
    tool: tools.echo
    inputs:
      message: steps.generate_summary.summary
```

### Workflow versioning

Every run records:
- `workflow_id`
- `workflow_version`
- `workflow_hash`
- `workflow_yaml` (full snapshot)

This enables safe workflow evolution and reproducible history.

Execution options:

```bash
# latest registered version in ./workflows
PYTHONPATH=src ./ai run code_review_agent -i issue="Login API fails"

# explicit version
PYTHONPATH=src ./ai run code_review_agent@v2 -i issue="Login API fails"

# direct file path still supported
PYTHONPATH=src ./ai run workflows/samples/versioning/code_review_agent_v1.yaml -i issue="Login API fails"
```

### Step fields

- `id`: unique step id
- `type`: `model` or `tool`
- `handler`: name of a registered handler function (for `model` steps). A handler is a Python function `(RuntimeState) -> dict` that does the actual work for the step — the runtime manages retries, state, and persistence around it.
- `tool`: tool name from registry (for `tool` steps)
- `inputs`: explicit state-to-input mapping
- `inputs` (contract mode): list of logical keys the step reads
- `outputs`: list of logical keys the step writes
- `retry`: optional attempts/backoff
- `next`: optional branching rules

### Step contracts (type-safe state boundaries)

You can declare read/write contracts per step:

```yaml
workflow:
  id: triage_contracts
  version: v1
inputs_contract: [issue]
steps:
  - id: generate_summary
    type: model
    handler: generate_summary
    inputs: [issue]
    outputs: [summary]
```

What runtime enforces:
- future-read prevention (step cannot read key not yet available)
- output collision prevention (two steps cannot declare same output key)
- output shape enforcement at execution (step output keys must match declared `outputs`)

### Retry block

```yaml
retry:
  attempts: 3
  backoff: exponential   # fixed | exponential
  initial_delay: 1
```

### Branching block

```yaml
next:
  - when: state.inputs.priority == "high"
    goto: urgent_path
  - default: fallback_path
```

## Runtime state contract

State is always structured:

```json
{
  "inputs": {},
  "steps": {},
  "runtime": {}
}
```

- `inputs`: immutable request context
- `steps`: per-step outputs (`steps.<step_id>`)
- `runtime`: runtime metadata

`RuntimeState` provides controlled APIs (`get`, `set`, `exists`, `delete`, `snapshot`, `diff`) while persistence remains JSON-compatible.

## Storage and observability

SQLite tables:

- `runs`
- `steps`
- `state_versions`

Step records include:

- `status`, `attempt_count`, `error`, `last_error`
- `state_before`, `state_after`
- `execution_index`, timing fields

This is what powers inspect, resume, and replay.

## Determinism guarantees (current)

- run stores `workflow_hash` and `input_hash`
- resume validates workflow integrity (hash lock — modified YAML blocks resume)
- replay uses persisted step data, not live external execution

## Current boundaries

Not in scope yet:

- LLM API call adapters (handlers return stub output; registry + config are ready)
- Memory tier persistence (interfaces wired, implementations are stubs)
- DAG scheduler / parallel execution
- full state schema/type enforcement
- advanced expression language beyond constrained eval
- idempotency keys for side-effecting tools
- tool sandboxing / permissions

## Run tests

```bash
PYTHONPATH=src pytest -q
```

## Project layout

- `src/agent_runtime/cli.py` - `ai` command surface
- `src/agent_runtime/config.py` - `runtime.yaml` config loader with CLI override support
- `src/agent_runtime/core.py` - executor and run/step lifecycle
- `src/agent_runtime/errors.py` - exception hierarchy (`WorkflowValidationError`, `StepExecutionError`, etc.)
- `src/agent_runtime/handler_discovery.py` - auto-discovery of handler functions from `handlers/` directory
- `src/agent_runtime/logging.py` - structured JSON logger
- `src/agent_runtime/replay.py` - deterministic replay engine
- `src/agent_runtime/resume.py` - resume-point resolution
- `src/agent_runtime/state.py` - runtime state manager (`RuntimeState`)
- `src/agent_runtime/steps.py` - step handler registry and built-in handlers
- `src/agent_runtime/utils.py` - hashing, state path resolution, safe expression eval
- `src/agent_runtime/workflow.py` - YAML parsing and validation
- `src/agent_runtime/workflow_registry.py` - workflow version resolution from directory scan
- `src/agent_runtime/agent/` - agent manifest system (`AgentManifest`, `validate_agent`, `export_agent`, `import_agent`)
- `src/agent_runtime/llm/` - LLM provider registry (`LLMRegistry`, `LLMProvider`, `ModelConfig`)
- `src/agent_runtime/memory/` - memory tier subsystem (`WorkingMemory`, `EpisodicMemory`, `SemanticMemory`, `ProceduralMemory`, `MemoryManager`)
- `src/agent_runtime/storage/` - persistence layer (abstract `Storage` + `SQLiteStorage`)
- `src/agent_runtime/tools/` - tool interface (`Tool`, `ToolResult`, `RuntimeContext`), registry, schema validation, discovery
- `src/agent_runtime/visualization/` - run visualization (`RunLoader`, `GraphBuilder`, `TimelineBuilder`, ASCII and HTML renderers)

## Additional docs

- `docs/USAGE.md`
- `docs/ARCHITECTURE.md`
- `docs/EXECUTION_WALKTHROUGH.md`
