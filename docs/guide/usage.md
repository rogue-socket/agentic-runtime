<!-- docs/guide/usage.md — command reference and scenario cookbook -->

# Usage

This guide is command-first and scenario-oriented. If you are brand new, start with [Getting Started](getting-started.md) and then return here.

## 1. Prerequisites

Use the shared conda environment and install the CLI in editable mode so `ai` is on your PATH:

```bash
conda activate agent_runtime
pip install -r requirements.txt
pip install -e .

```

## 2. Create a new agent project

Pick a folder for your agent. The runtime uses the current directory as the project root.

```bash
mkdir my-agent
cd my-agent
ai quickstart
```

`ai quickstart` initializes the project (if needed), configures an LLM provider, writes `.env`, and runs a starter workflow.

This keeps the same onboarding flow and guarantees a first successful run without external credentials. Supported samples: `starter`, `branching`, `research`, `pipeline`.


Advanced alternatives (optional):

```bash
ai init
```

Run the wizard from another directory:

```bash
ai onboard --path my-project
```

When run with no args, `ai` opens a home screen with common actions (setup, run sample, inspect, visualize).

Creates a project structure:

```
├── workflows/
│   └── example.yaml           # example workflow definition
├── agents/
│   ├── summarizer.yaml        # example agent definition
│   └── fixer.yaml             # example agent definition
├── functions/
│   └── stubs.py               # example function step implementations
├── tools/
│   └── example_tool.py        # example tool implementation
└── runtime.yaml               # runtime configuration
```

- `workflows/` — YAML workflow definitions (orchestrate agents, functions, and tools)
- `agents/` — YAML agent definitions (LLM model, strategy, pipeline)
- `functions/` — Python functions for `function` steps (`(inputs: dict) -> dict`)
- `tools/` — Python classes implementing the `Tool` protocol for `tool` steps
- `runtime.yaml` — runtime configuration (db path, directory paths, LLM providers)

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

The `inputs:` block declares what the workflow expects from the caller. Inputs can specify `description`, `required` (default `true`), and `default`.

**Shorthand Syntax**:
A list form is also supported: `inputs: [issue, priority]`. This implies all listed fields are `required: true` with no defaults.


Workflows without an `inputs:` block still work — the runtime infers available inputs from step references (backward compatible).

## Run default example

```bash
ai run workflows/example.yaml
```

## Run latest workflow version by id

```bash
ai run example_workflow
```

Resolution rule:
- runtime scans `./workflows/**/*.yaml` and `./workflows/**/*.yml`
- selects highest numeric `vN` for matching `workflow.id`

## Run a specific workflow version

```bash
ai run code_review_agent@v2
```

## Run with custom inputs

Pass inputs with the `-i` / `--input` flag (repeatable):

```bash
ai run workflows/example.yaml -i issue="Login API fails for invalid token"
ai run code_review_agent@v1 -i issue="Login API fails for invalid token"
```

Multiple inputs:

```bash
ai run my_workflow.yaml -i issue="bug report" -i priority="high"
```

If the workflow declares defaults, you can omit inputs that have them.

## Run with verbose logging

By default, only compact progress lines are shown. For full structured JSON event logs (LLM calls, tool invocations, timing, token usage), add `-v` / `--verbose`:

```bash
ai run workflows/example.yaml -v
```

## Use a custom SQLite path

```bash
ai run workflows/example.yaml --db-path runtime.db
```

## 4. Inspect runs

## Summary mode

```bash
ai inspect <run_id>
```

Use when you want:
- run status
- ordered step outcome
- latest state snapshot

## Step-centric mode

```bash
ai inspect <run_id> --steps
```

Use when you want:
- per-step output
- attempt counts
- exact error details

## State evolution mode

```bash
ai inspect <run_id> --state-history
```

Use when you want:
- initial state
- per-step mutation history
- state diffs and post-step snapshots

## 5. Resume failed runs

```bash
ai resume <run_id>
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
ai replay <run_id>
```

## Replay with consistency verification

```bash
ai replay <run_id> --verify-state
```

## Replay until a specific step

```bash
ai replay <run_id> --until summarize
```

## Replay interactively (step-by-step)

```bash
ai replay <run_id> --step-by-step
```

Replay guarantees:
- no tool invocation
- no agent invocation
- no persisted data mutation

## 7. Sample workflows

Run all curated samples:

```bash
ai run workflows/samples/01_linear_issue_summary.yaml
ai run workflows/samples/02_retry_and_backoff.yaml
ai run workflows/samples/03_branching_triage.yaml -i issue="bug"
ai run workflows/samples/04_fail_and_resume.yaml -i issue="Login API fails"
ai run workflows/samples/versioning/code_review_agent_v1.yaml
ai run workflows/samples/versioning/code_review_agent_v2.yaml
```

What each sample demonstrates:
- `01_linear_issue_summary.yaml`: baseline linear execution (function steps)
- `02_retry_and_backoff.yaml`: retry semantics and attempt visibility
- `03_branching_triage.yaml`: deterministic conditional branching
- `04_fail_and_resume.yaml`: failure path and resume flow
- `05_llm_call.yaml`: agent steps with LLM provider (uses `output_key` for downstream references)
- `06_gemini_call.yaml`: agent steps with Gemini provider
- `07_agent_and_function.yaml`: mixed agent + function + tool steps with output contracts
- `versioning/code_review_agent_v1.yaml` + `v2`: workflow version evolution

## 8. Step types and authoring

### Writing a function

A function is a Python callable that does deterministic work for a `function` step. The runtime calls it with the step's inputs and expects a dict back.

Signature:
```python
def my_function(inputs: dict) -> dict:
    # read inputs
    # do work (transform data, classify, format, etc.)
    # return a dict of outputs
```

Example — a function that classifies issue severity:
```python
# functions/classifiers.py

def classify_severity(inputs: dict) -> dict:
    issue = inputs.get("issue", "").lower()
    if "crash" in issue or "down" in issue:
        return {"severity": "critical", "reason": "Service impact detected"}
    return {"severity": "low", "reason": "No immediate impact"}
```

Using a function in a workflow:
```yaml
steps:
  - id: triage
    type: function
    function: classifiers.classify_severity
    inputs:
      issue: inputs.issue
```

When this step runs, the runtime:
1. Resolves `classifiers.classify_severity` from `functions/classifiers.py`
2. Builds the input dict from the `inputs` mapping
3. Calls `classify_severity(inputs)`
4. Writes the returned dict to `steps.triage` in state
5. Persists `state_before`, `state_after`, timing, and attempt count to SQLite

### Writing an agent definition

An agent definition describes an LLM-backed reasoning unit. It lives in `agents/` as a YAML file.

### Model Resolution Hierarchy
The runtime resolves the model for an agent step in this order:
1.  **CLI Flag**: `--model <id>` (passed to `ai run`)
2.  **Agent YAML**: `model: <id>` (defined in `agents/*.yaml`)
3.  **Runtime Config**: `default_model: <id>` (defined in `runtime.yaml`)
4.  **Provider Default**: (e.g., `gpt-4o`)

```yaml
# agents/reviewer.yaml
agent:
  id: reviewer
  version: v1
  model: gpt-4o-mini             # Optional: overrides default_model
  system: "You are a senior code reviewer."

  output_key: review              # downstream steps read via steps.review.review
  strategy:
    type: react
    max_iterations: 5
  tools:
    - tools.file
  temperature: 0.2
  max_tokens: 4096
  pipeline:
    - id: analyze
      type: model
      prompt: "Analyze this diff for issues: {{ inputs.diff }}"
    - id: review
      type: model
      prompt: "Write a complete review based on: {{ analyze.text }}"
```

Using an agent in a workflow:
```yaml
steps:
  - id: review
    type: agent
    agent: reviewer
    inputs:
      diff: inputs.pr_diff
```

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

Built-in tools (`tools.echo`, `tools.http`, `tools.file`, `tools.shell`) are always available regardless of what's in `tools/`.

### Choosing a step type

| | `type: function` | `type: agent` | `type: tool` |
|---|---|---|---|
| **When** | Deterministic logic | LLM reasoning needed | External side effects |
| **Where** | `functions/` | `agents/` | `tools/` |
| **Signature** | `(dict) -> dict` | Agent YAML | Tool protocol class |
| **Examples** | Parsing, formatting, classification | Summarizing, reviewing, planning | HTTP calls, file I/O, shell |

### Using step contracts

```yaml
workflow:
  id: contracts_demo
  version: v1
inputs: [issue]
steps:
  - id: classify
    type: function
    function: stubs.classify_severity
    inputs: [issue]
    outputs: [severity]
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
ai run workflows/samples/04_fail_and_resume.yaml -i issue="Login API fails"
ai inspect <run_id> --steps
ai inspect <run_id> --state-history
```

## B) Recover after fixing an adapter/config

```bash
ai resume <run_id>
```

## C) Reproduce exactly for postmortem

```bash
ai replay <run_id> --verify-state --step-by-step
```

## 10. Test suite

```bash
pytest -q
```

For targeted checks:

```bash
pytest -q tests/test_replay.py
pytest -q tests/test_state_manager.py
```

## 11. Runtime configuration

The runtime reads settings from `runtime.yaml` in the project root. CLI flags override config values.

Example `runtime.yaml` (generated by `ai init`):

```yaml
db_path: runtime.db
workflows_dir: workflows
tools_dir: tools
agents_dir: agents
functions_dir: functions

# llm:
#   providers:
#     openai:
#       api_key_env: OPENAI_API_KEY
#       models:
#         gpt-4o:
#           temperature: 0.2
#           max_tokens: 4096
#     anthropic:
#       api_key_env: ANTHROPIC_API_KEY
#       models:
#         claude-3-opus:
#           temperature: 0.3
#     gemini:
#       api_key_env: GEMINI_API_KEY
#       models:
#         gemini-2.5-flash:
#           temperature: 0.2
#           max_tokens: 8192

# logging:
#   level: info
#   format: json
```

Tip: `ai setup` can scaffold this config and write `.env`, and `ai setup --check` validates which provider keys are available.

Precedence: `--db-path` flag > `runtime.yaml` value > built-in default (`runtime.db`).

If `runtime.yaml` does not exist, all built-in defaults apply.

## 12. Troubleshooting

Troubleshooting is now in [Troubleshooting](troubleshooting.md).

## 13. State diff debugging

Show state changes across all recorded steps:

```bash
ai state-diff <run_id>
```

Show state changes for one step id:

```bash
ai state-diff <run_id> --step plan
```

Output markers:
- `+` added key path
- `-` removed key path
- `~` modified key path

## 14. Run visualization

ASCII graph + timeline:

```bash
ai visualize <run_id> --ascii
```

Timeline-focused text:

```bash
ai visualize <run_id> --timeline
```

HTML visualization (default mode, auto-opens browser):

```bash
ai visualize <run_id>
```

HTML visualization with explicit HTML mode (also auto-opens browser):

```bash
ai visualize <run_id> --html
```

## 15. List agents

```bash
Lists all agent definitions found in `agents/` with their id and version.

## 16. Aggregate Metrics

```bash
ai metrics
```

Shows health statistics across all runs in your database:
- **Success Rate**: % of runs that reached `RUN_COMPLETE`.
- **Latency (p95)**: The 95th percentile duration for successful runs.
- **Top Errors**: Frequency table of the most common `STEP_ERROR` causes.
- **Trend**: Health change over the last `--window-days` (default 7).

## 17. Documentation Management

```bash
ai docs
```

The `ai docs` command is the engine behind the automated documentation site.
- **Workflow Reference**: Automatically generates `docs/guide/workflow-reference-generated.md` by scanning your `workflows/` directory.
- **Search Index**: Rebuilds `docs/content.js` and `docs/docs-manifest.json` for the web UI.

