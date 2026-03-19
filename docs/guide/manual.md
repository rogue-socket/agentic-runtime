**Agentic Runtime Manual**

Welcome. This manual is written for first-time users and for people who want a complete reference in one place. If you only read one document, read this one.

**Mental Model**

A workflow is a recipe. Each step reads the current state, does some work, then writes new fields back to the state. The runtime records every step, every state change, and every error, so runs can be inspected, resumed, or replayed later.

**Core Concepts**

- Workflow: a YAML file that describes inputs and steps.
- Step: a unit of work in the workflow.
- State: the structured data passed between steps.
- Handler: a Python function used by `model` steps.
- Tool: a Python class used by `tool` steps.
- Agent manifest: a portable bundle that references a workflow plus its handlers and tools.
- Run: a persisted execution record stored in SQLite.

**Quickstart**

```bash
mkdir my-agent
cd my-agent
ai quickstart
```

This creates the project structure, configures your LLM provider, and runs the starter workflow.

**Project Structure**

```
my-agent/
  agents/
  handlers/
  tools/
  workflows/
  runtime.yaml
  .env
```

**Writing A Workflow**

Minimum shape:

```yaml
workflow:
  id: my_workflow
  version: v1
inputs:
  issue:
    description: The issue text
    required: true
steps:
  - id: summarize
    type: model
    handler: generate_summary
    inputs:
      issue: inputs.issue
```

Referencing data:

- `inputs.<name>` reads workflow inputs.
- `steps.<step_id>.<field>` reads prior step output.

Branching:

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

Retry policy:

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

Error handling:

- `on_error: fail_fast` stops on the first error.
- `on_error: continue` attempts the remaining steps.

Versioning:

```bash
ai run my_workflow
ai run my_workflow@v2
```

**Handlers (Model Steps)**

Handler functions live in `handlers/` and are auto-discovered.

```python
from agent_runtime.state import RuntimeState

def summarize_issue(state: RuntimeState) -> dict:
    issue = state.get("issue", "")
    return {"summary": issue[:140]}
```

Workflow usage:

```yaml
steps:
  - id: summarize
    type: model
    handler: summarize_issue
    inputs:
      issue: inputs.issue
```

**Tools (Tool Steps)**

Tool classes live in `tools/` and are auto-discovered.

```python
from __future__ import annotations

from typing import Any, Dict, Optional
from agent_runtime.tools.base import RuntimeContext, ToolResult

class ExampleTool:
    name = "tools.example"
    description = "Uppercases the provided text"
    input_schema = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }
    timeout: Optional[float] = None
    retries: Optional[int] = None

    async def execute(
        self, input: Dict[str, Any], context: RuntimeContext
    ) -> ToolResult:
        text = input.get("text", "")
        return ToolResult(success=True, output={"text": text.upper()}, error=None, metadata=None)
```

Workflow usage:

```yaml
steps:
  - id: shout
    type: tool
    tool: tools.example
    inputs:
      text: inputs.message
```

**Running Workflows**

```bash
ai run workflows/example.yaml
ai run workflows/example.yaml -i issue="Login API fails for invalid token"
```

**Inspecting Runs**

```bash
ai inspect <run_id> --steps
ai visualize <run_id> --html
```

**Resuming And Replaying**

```bash
ai resume <run_id>
ai replay <run_id> --verify-state
```

**Common Errors**

- Unknown handler: confirm the function name is public and in `handlers/`.
- Unknown tool: confirm the tool class has a `name` and is in `tools/`.
- Missing inputs: add `-i key=value` or set defaults in the workflow.
- YAML errors: run `ai validate <agent.yaml>` or fix indentation issues.

**Security And Safety**

- Keep API keys in `.env` or environment variables, not in code.
- Use shell allowlists in `runtime.yaml` if you enable the shell tool.

If you want deeper reference material, see `docs/guide/usage.md` and `docs/guide/workflows.md`.
