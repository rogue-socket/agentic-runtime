**Writing Workflows (Explained Simply)**

Think of a workflow as a checklist. The runtime reads the list top to bottom, runs each step, and saves the results into state.

If you are new, remember one sentence:
**A workflow is a YAML file that describes inputs and steps.**

**What A Workflow Does**

1. Declare inputs (what data you expect).
2. Run steps in order.
3. Store each step output in state.
4. Let later steps read earlier outputs.

**Basic Shape**

```yaml
workflow:                     # workflow metadata
  id: issue_triage             # unique workflow id
  version: v1                  # version tag
inputs:                        # declared inputs
  issue:
    description: The issue text to analyze
    required: true             # required input
on_error: fail_fast            # stop on first error
steps:                         # ordered steps (a list)
  - id: summarize              # agent step — calls an LLM agent
    type: agent
    agent: summarizer           # defined in agents/summarizer.yaml
    inputs:
      issue: inputs.issue       # read from inputs
  - id: classify               # function step — calls a Python function
    type: function
    function: stubs.classify_severity
    inputs:
      issue: inputs.issue
  - id: echo                   # tool step — calls a tool class
    type: tool
    tool: tools.echo
    inputs:
      message: steps.summarize.summary  # read prior step output
```

Note on the `-` character: in YAML it means "this is a list item." You need `-` for each step and for each branch rule because those are lists.

**Inputs**

Inputs tell the runtime what data you will pass at run time.

- `inputs` is optional.
- If you declare `inputs`, the runtime validates what you pass.
- If you do not declare `inputs`, anything you pass is accepted.

Example run:

```bash
ai run workflows/example.yaml -i issue="Login API fails for invalid token"
```

**How Data Moves**

- `inputs.<name>` reads workflow inputs.
- `steps.<step_id>.<field>` reads outputs from a prior step.

Each step type controls its output keys differently:

- **Function steps** — the Python function returns a dict; its keys become the output. E.g. `return {"severity": "critical"}` → `steps.classify.severity`.
- **Tool steps** — the `ToolResult.output` dict keys become the output. E.g. `output={"priority": "P1"}` → `steps.priority.priority`.
- **Agent steps** — when the LLM returns plain text, the runtime wraps it as `{output_key: "..."}` where `output_key` is set in the agent YAML (default: `text`). E.g. agent with `output_key: summary` → `steps.summarize.summary`.

Example:

```yaml
inputs:
  issue:
    required: true
steps:
  - id: summarize
    type: agent
    agent: summarizer
    inputs:
      issue: inputs.issue
  - id: classify
    type: function
    function: stubs.classify_severity
    inputs:
      summary: steps.summarize.summary
```

**Step Types**

`agent` step:
- Delegates to an agent definition in `agents/`.
- The agent runs its LLM pipeline internally and returns outputs.
- Use this when you need a language model.

`function` step:
- Calls a plain Python function in `functions/`.
- Signature: `(inputs: dict) -> dict`.
- Use this for deterministic logic and transformations.

`tool` step:
- Calls a tool class in `tools/`.
- Use this for external actions (HTTP, filesystem, shell, APIs).

**Retry Policy**

```yaml
steps:
  - id: unstable_call
    type: tool
    tool: tools.http
    inputs:
      url: inputs.url
    retry:
      attempts: 3
      backoff: exponential
      initial_delay: 1
```

**Branching**

Branching lets you jump to another step based on a condition.

```yaml
steps:
  - id: classify
    type: function
    function: stubs.classify_severity
    inputs:
      issue: inputs.issue
    next:
      - when: state.inputs.issue == "bug"
        goto: bug_path
      - when: state.inputs.issue == "feature"
        goto: feature_path
      - default: default_path
```

Branch targets must point to valid step ids. The runtime validates this at load time.

**Error Policy**

Workflow-level `on_error` can be:
- `fail_fast` (default) stops on the first error.
- `continue` attempts the remaining steps.

**Versioning**

Use `workflow.version` like `v1`, `v2`, etc. The CLI resolves the highest version when you run by id:

```bash
ai run issue_triage
ai run issue_triage@v2
```

**Common Mistakes (Quick Fixes)**

- Forgot `-` before a step: YAML will parse incorrectly.
- Used a file path instead of a reference: `function: my_functions.summarize` not `function: functions/my_functions.py`.
- Referenced `steps.x` before it runs: only read outputs from earlier steps.

For deeper function, agent, and tool coverage, see [Writing Agents](writing-agents.md), [Writing Functions](writing-functions.md), and [Writing Tools](writing-tools.md).
