# Usage

This guide is command-first and scenario-oriented.

## 1. Prerequisites

- Use conda env: `agent_runtime`
- Install dependencies:

```bash
pip install -r requirements.txt
```

## 2. Initialize project scaffold

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
└── runtime.yaml               # runtime configuration
```

- `workflows/` — YAML workflow definitions
- `handlers/` — Python functions for `model` step handlers
- `tools/` — Python classes implementing the `Tool` protocol for `tool` steps
- `runtime.yaml` — runtime configuration (db path, directory paths, model backend settings)

## 3. Run workflows

Workflow files should declare:

```yaml
workflow:
  id: my_workflow
  version: v1
inputs:
  issue:
    description: The issue text to process
    required: true
  priority:
    description: Optional priority level
    required: false
    default: "medium"
```

The `inputs:` block declares what the workflow expects from the caller.
Inputs can specify `description`, `required` (default `true`), and `default`.
A shorthand list form is also supported: `inputs: [issue, priority]` (all required, no defaults).

Workflows without an `inputs:` block still work — the runtime infers
available inputs from step references (backward compatible).

## Run default example

```bash
PYTHONPATH=src ./ai run workflows/example.yaml
```

## Run latest workflow version by id

```bash
PYTHONPATH=src ./ai run example_workflow
```

Resolution rule:
- runtime scans `./workflows/**/*.yaml` and `./workflows/**/*.yml`
- selects highest numeric `vN` for matching `workflow.id`

## Run a specific workflow version

```bash
PYTHONPATH=src ./ai run code_review_agent@v2
```

## Run with custom inputs

Pass inputs with the `-i` / `--input` flag (repeatable):

```bash
PYTHONPATH=src ./ai run workflows/example.yaml -i issue="Login API fails for invalid token"
PYTHONPATH=src ./ai run code_review_agent@v1 -i issue="Login API fails for invalid token"
```

Multiple inputs:

```bash
PYTHONPATH=src ./ai run my_workflow.yaml -i issue="bug report" -i priority="high"
```

If the workflow declares defaults, you can omit inputs that have them.

## Use a custom SQLite path

```bash
PYTHONPATH=src ./ai run workflows/example.yaml --db-path runtime.db
```

## 4. Inspect runs

## Summary mode

```bash
PYTHONPATH=src ./ai inspect <run_id>
```

Use when you want:
- run status
- ordered step outcome
- latest state snapshot

## Step-centric mode

```bash
PYTHONPATH=src ./ai inspect <run_id> --steps
```

Use when you want:
- per-step output
- attempt counts
- exact error details

## State evolution mode

```bash
PYTHONPATH=src ./ai inspect <run_id> --state-history
```

Use when you want:
- initial state
- per-step mutation history
- state diffs and post-step snapshots

## 5. Resume failed runs

```bash
PYTHONPATH=src ./ai resume <run_id>
```

Use when:
- a run failed mid-flow
- completed steps should not re-run

Behavior:
- validates run status and workflow compatibility
- restores latest state
- continues from resume step

## 6. Deterministic replay

## Replay full run

```bash
PYTHONPATH=src ./ai replay <run_id>
```

## Replay with consistency verification

```bash
PYTHONPATH=src ./ai replay <run_id> --verify-state
```

## Replay until a specific step

```bash
PYTHONPATH=src ./ai replay <run_id> --until summarize
```

## Replay interactively (step-by-step)

```bash
PYTHONPATH=src ./ai replay <run_id> --step-by-step
```

Replay guarantees:
- no tool invocation
- no model invocation
- no persisted data mutation

## 7. Sample workflows

Run all curated samples:

```bash
PYTHONPATH=src ./ai run workflows/samples/01_linear_issue_summary.yaml
PYTHONPATH=src ./ai run workflows/samples/02_retry_and_backoff.yaml
PYTHONPATH=src ./ai run workflows/samples/03_branching_triage.yaml -i issue="bug"
PYTHONPATH=src ./ai run workflows/samples/04_fail_and_resume.yaml -i issue="Login API fails"
PYTHONPATH=src ./ai run workflows/samples/versioning/code_review_agent_v1.yaml
PYTHONPATH=src ./ai run workflows/samples/versioning/code_review_agent_v2.yaml
```

What each sample demonstrates:
- `01_linear_issue_summary.yaml`: baseline linear execution
- `02_retry_and_backoff.yaml`: retry semantics and attempt visibility
- `03_branching_triage.yaml`: deterministic conditional branching
- `04_fail_and_resume.yaml`: failure path and resume flow
- `versioning/code_review_agent_v1.yaml` + `versioning/code_review_agent_v2.yaml`: workflow version evolution

## 8. Step contracts workflow pattern

### Writing a handler

A handler is a Python function that does the actual work for a `model` step. The runtime calls it, passing in the step's input state, and expects a dict back.

Signature:
```python
def my_handler(state: RuntimeState) -> Dict[str, Any]:
    # read inputs from state
    # do work (call an LLM, transform data, etc.)
    # return a dict of outputs
```

Example — a handler that classifies issue severity:
```python
def classify_severity(state: RuntimeState) -> Dict[str, Any]:
    issue = state["issue"]
    if "crash" in issue.lower() or "down" in issue.lower():
        return {"severity": "critical", "reason": "Service impact detected"}
    return {"severity": "low", "reason": "No immediate impact"}
```

### Handler auto-discovery

The runtime automatically discovers handlers from the `handlers/` directory. Just drop a `.py` file there and your handlers are available.

**Convention 1 — zero-config:** every public function (not starting with `_`) is registered using the function name.

```
handlers/
└── my_handlers.py     # contains classify_severity() → available as handler: classify_severity
```

**Convention 2 — explicit:** define a `__handlers__` dict for full naming control.

```python
# handlers/my_handlers.py

def _internal_helper():
    pass

def _my_classify(state):
    return {"severity": "low", "reason": "No impact"}

__handlers__ = {
    "classify_severity": _my_classify,
}
```

Built-in handlers (`generate_summary`, `classify_severity`, `diagnose_issue`, `propose_fix`, `review_code`) are always available regardless of what's in `handlers/`.

Using a handler in a workflow:
```yaml
steps:
  - id: triage
    type: model
    handler: classify_severity
    inputs:
      issue: inputs.issue
```

When this step runs, the runtime:
1. Builds the input state from the `inputs` mapping
2. Calls `classify_severity(input_state)`
3. Writes the returned dict to `steps.triage` in state
4. Persists `state_before`, `state_after`, timing, and attempt count to SQLite

Handlers vs tools:
- **Handlers** = plain Python functions for `model` steps (type: `model`, field: `handler`)
- **Tools** = objects implementing the `Tool` protocol for `tool` steps (type: `tool`, field: `tool`)

### Writing a tool

Tools are classes that implement the `Tool` protocol. Drop a `.py` file in `tools/` and the runtime discovers it automatically.

Tool protocol:
```python
class MyTool:
    name = "tools.my_tool"             # unique tool name
    description = "What this tool does"
    input_schema = {                    # JSON Schema for input validation
        "type": "object",
        "properties": {
            "message": {"type": "string"},
        },
    }
    timeout: Optional[float] = None     # optional execution timeout
    retries: Optional[int] = None       # optional retry count

    async def execute(self, input: Dict[str, Any], context: RuntimeContext) -> ToolResult:
        # Do work here (API call, file operation, etc.)
        return ToolResult(success=True, output={"result": "..."},
                          error=None, metadata=None)
```

Discovery convention: every class whose name doesn't start with `_` and satisfies the protocol is auto-registered. No manual registration needed.

Using a tool in a workflow:
```yaml
steps:
  - id: shout
    type: tool
    tool: tools.my_tool
    inputs:
      message: inputs.text
```

Built-in tools (`tools.echo`) are always available regardless of what's in `tools/`.

### Using step contracts

```yaml
workflow:
  id: contracts_demo
  version: v1
inputs_contract: [issue]
steps:
  - id: generate_summary
    type: model
    handler: generate_summary
    inputs: [issue]
    outputs: [summary]
```

Behavior:
- Contract input keys are validated against available state symbols.
- Contract output keys are checked for collisions across steps.
- Runtime enforces that step output keys match declared `outputs`.

## 9. Common workflows for developers

## A) Debug a failure

1. Run workflow.
2. Inspect step details.
3. Inspect state history.

```bash
PYTHONPATH=src ./ai run workflows/samples/04_fail_and_resume.yaml -i issue="Login API fails"
PYTHONPATH=src ./ai inspect <run_id> --steps
PYTHONPATH=src ./ai inspect <run_id> --state-history
```

## B) Recover after fixing an adapter/config

```bash
PYTHONPATH=src ./ai resume <run_id>
```

## C) Reproduce exactly for postmortem

```bash
PYTHONPATH=src ./ai replay <run_id> --verify-state --step-by-step
```

## 10. Test suite

```bash
PYTHONPATH=src pytest -q
```

For targeted checks:

```bash
PYTHONPATH=src pytest -q tests/test_replay.py
PYTHONPATH=src pytest -q tests/test_state_manager.py
```

## 11. Runtime configuration

The runtime reads settings from `runtime.yaml` in the project root. CLI flags override config values.

Example `runtime.yaml` (generated by `ai init`):

```yaml
db_path: runtime.db
workflows_dir: workflows
handlers_dir: handlers
tools_dir: tools

# model:
#   provider: openai
#   model: gpt-4
#   temperature: 0.2
#   max_tokens: 4096
#   api_key_env: OPENAI_API_KEY

# logging:
#   level: info
#   format: json
```

Precedence: `--db-path` flag > `runtime.yaml` value > built-in default (`runtime.db`).

If `runtime.yaml` does not exist, all built-in defaults apply.

## 12. Troubleshooting

## `Cannot replay RUNNING run`
- Wait for run completion/failure, then replay.

## `Workflow hash mismatch; cannot resume`
- Workflow changed since original run.
- Resume requires compatible workflow definition.

## `Replay data missing`
- Step/state persistence is incomplete for that run.
- Re-run workflow with current runtime version.

## `ModuleNotFoundError: yaml`
- Install dependencies in the active environment:

```bash
pip install -r requirements.txt
```

## 13. State diff debugging

Show state changes across all recorded steps:

```bash
PYTHONPATH=src ./ai state-diff <run_id>
```

Show state changes for one step id:

```bash
PYTHONPATH=src ./ai state-diff <run_id> --step plan
```

Output markers:
- `+` added key path
- `-` removed key path
- `~` modified key path

## 14. Run visualization

ASCII graph + timeline:

```bash
PYTHONPATH=src ./ai visualize <run_id> --ascii
```

Timeline-focused text:

```bash
PYTHONPATH=src ./ai visualize <run_id> --timeline
```

HTML visualization (default mode, auto-opens browser):

```bash
PYTHONPATH=src ./ai visualize <run_id>
```

HTML visualization without auto-opening browser:

```bash
PYTHONPATH=src ./ai visualize <run_id> --html
```

Output:
- file path `.runs/<run_id>/visualization.html`
- default mode attempts to open the file in the default browser
- `--html` generates the file without opening the browser

HTML includes:
- execution graph view
- branch decision table
- step timeline with attempts/duration
- tool call table (args/result/latency)
- state timeline with per-step diffs
