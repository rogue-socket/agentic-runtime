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
  - id: summarize              # list item 1
    type: model                # model step uses a handler
    handler: generate_summary  # handler function name
    inputs:
      issue: inputs.issue      # read from inputs
  - id: echo                   # list item 2
    type: tool                 # tool step uses a tool class
    tool: tools.echo           # tool name
    inputs:
      message: steps.summarize.summary  # read prior step output
```

Note on the `-` character: in YAML it means “this is a list item.” You need `-` for each step and for each branch rule because those are lists.

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

Example:

```yaml
inputs:
  issue:
    required: true             # required input
steps:
  - id: summarize
    type: model
    handler: generate_summary
    inputs:
      issue: inputs.issue      # input reference
  - id: classify
    type: model
    handler: classify_severity
    inputs:
      summary: steps.summarize.summary  # step output reference
```

**Step Types**

`model` step:
- Calls a handler function (a Python function in `handlers/`).
- Use this for logic and transformations.

`tool` step:
- Calls a tool class (a Python class in `tools/`).
- Use this for external actions (HTTP, filesystem, shell, APIs).

**Retry Policy**

```yaml
steps:
  - id: unstable_call
    type: tool                 # tool step
    tool: tools.http            # built-in HTTP tool
    inputs:
      url: inputs.url           # input reference
    retry:
      attempts: 3               # retry count
      backoff: exponential      # backoff strategy
      initial_delay: 1          # seconds
```

**Branching**

Branching lets you jump to another step based on a condition.

```yaml
steps:
  - id: triage
    type: model                 # model step
    handler: classify_severity  # handler function
    inputs:
      issue: inputs.issue       # input reference
    branch:
      when:
        - if: steps.triage.severity == "high"  # branch condition
          goto: escalate                        # jump target step id
        - if: steps.triage.severity == "low"
          goto: close
```

Branches must point to valid step ids. The runtime validates this at load time.

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
- Used `handler: handlers/my_handler.py`: handler should be the function name, not a path.
- Referenced `steps.x` before it runs: only read outputs from earlier steps.

For deeper handler and tool coverage, see [Handlers](handlers.md) and [Tools](tools.md).
