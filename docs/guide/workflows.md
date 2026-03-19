**Writing Workflows**

If you are new here, think of a workflow as a recipe. Each step reads from the current state, does a unit of work, then writes new fields back into the state for later steps to use.

This guide covers the workflow YAML format, the step types, and the patterns you will use most often.

**Basic Shape**

```yaml
workflow:
  id: issue_triage
  version: v1
inputs:
  issue:
    description: The issue text to analyze
    required: true
on_error: fail_fast
steps:
  - id: summarize
    type: model
    handler: generate_summary
    inputs:
      issue: inputs.issue
  - id: echo
    type: tool
    tool: tools.echo
    inputs:
      message: steps.summarize.summary
```

**Inputs**

- `inputs` declares what the workflow expects from the caller.
- Each input can define `description`, `required` (default `true`), and `default`.
- If you omit `inputs`, the runtime will accept any inputs passed by the caller.

Example call:

```bash
ai run workflows/example.yaml -i issue="Login API fails for invalid token"
```

**Step Types**

`model` step:
- Uses a handler function registered in `handlers/` or built in.
- `handler` is the handler name, not a file path.

`tool` step:
- Uses a tool class registered in `tools/`.
- `tool` is the tool name (for example `tools.echo`).

**Referencing Data**

Use `inputs.<name>` to read workflow inputs and `steps.<step_id>.<field>` to read prior outputs.

Example:

```yaml
inputs:
  issue:
    required: true
steps:
  - id: summarize
    type: model
    handler: generate_summary
    inputs:
      issue: inputs.issue
  - id: classify
    type: model
    handler: classify_severity
    inputs:
      summary: steps.summarize.summary
```

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

```yaml
steps:
  - id: triage
    type: model
    handler: classify_severity
    inputs:
      issue: inputs.issue
    branch:
      when:
        - if: steps.triage.severity == "high"
          goto: escalate
        - if: steps.triage.severity == "low"
          goto: close
```

Branches must point to valid step ids. The runtime will validate this at load time.

**Error Policy**

Workflow-level `on_error` can be:
- `fail_fast` (default)
- `continue` (attempts to complete remaining steps)

**Versioning**

Use `workflow.version` like `v1`, `v2`, etc. The CLI resolves the highest version when you run by id:

```bash
ai run issue_triage
ai run issue_triage@v2
```

**Handlers And Tools**

- Put handler functions in `handlers/`. Public functions are auto-registered.
- Put tools in `tools/`. Public classes implementing the Tool protocol are auto-registered.

If you change handlers or tools, re-run the same workflow file and the runtime will discover the new code.

For deeper handler and tool coverage, see `docs/guide/handlers.md` and `docs/guide/tools.md`.
