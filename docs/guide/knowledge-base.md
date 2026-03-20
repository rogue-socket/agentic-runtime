**Knowledge Base**

This page explains what the runtime is, what workflows, agents, functions, and tools are, and how they fit together.

**What This Is**

`agentic-runtime` is an execution runtime for AI agent workflows. You define a workflow in YAML, the runtime executes each step deterministically, and it records every state change so you can inspect, resume, and replay runs.

**Core Building Blocks**

- Workflow: the YAML recipe that describes inputs and steps.
- Function: a Python callable that powers a `function` step.
- Agent: an LLM-backed definition that powers an `agent` step.
- Tool: a Python class that powers a `tool` step.
- State: the structured data that flows between steps.
- Run: a persisted execution record stored in SQLite.

**Agent Definitions vs Workflow Definitions**

- Workflow definition: the YAML file in `workflows/` that defines inputs and steps.
- Agent definition: the YAML file in `agents/` that describes an LLM agent's model, strategy, tools, and pipeline.

Think of it like this:
The **workflow** is the recipe, and the **agent** is the packaged meal kit that says which recipe to run and what ingredients to include.

**How They Tie Together**

1. You write a workflow (`workflows/my_workflow.yaml`).
2. The workflow references agents, functions, and tools by name.
3. The runtime loads the workflow and builds the step registry.
4. When it reaches an `agent` step, it resolves the agent definition and runs its LLM pipeline.
5. When it reaches a `function` step, it calls the Python function.
6. When it reaches a `tool` step, it calls the tool's `execute()` method.
7. Each step runs in order (with branching/retries if configured).
8. Every step output is merged into state and persisted.

**Visual Summary**

```text
Workflow YAML
  ├─ Inputs (initial state)
  ├─ Steps
  │   ├─ agent step    → Agent definition (LLM pipeline)
  │   ├─ function step → Python function
  │   └─ tool step     → Tool class
  └─ Outputs (state after each step)

Runtime
  ├─ Executes steps
  ├─ Persists run + state
  └─ Enables inspect / resume / replay
```

**Workflows**

Workflows define the sequence of steps and how data flows.

Example:

```yaml
workflow:                     # workflow metadata
  id: issue_triage             # unique id
  version: v1                  # version tag
inputs:                        # declared inputs
  issue:
    required: true             # required input
steps:                         # ordered steps
  - id: summarize
    type: agent                # agent step uses an LLM agent
    agent: summarizer          # agent id from agents/
    inputs:
      issue: inputs.issue      # input reference
  - id: echo
    type: tool                 # tool step uses a tool class
    tool: tools.echo           # tool name
    inputs:
      message: steps.summarize.summary  # step output reference
```

**Functions**

Functions are plain Python callables. They receive an inputs dict and return a dictionary of outputs.

```python
def summarize_issue(inputs: dict) -> dict:
    issue = inputs.get("issue", "")
    return {"summary": issue[:140]}
```

**Tools**

Tools are Python classes that perform external actions.

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
        text = input.get("text", "")  # read tool input
        return ToolResult(             # return tool result
            success=True,
            output={"text": text.upper()},
            error=None,
            metadata=None,
        )
```

**State And Data Flow**

- Inputs are accessed as `inputs.<name>`.
- Step outputs are accessed as `steps.<step_id>.<field>`.
- Each step result is stored under `steps.<step_id>` in state.

**Where To Learn More**

- [Getting Started](getting-started.md)
- [Manual](manual.md)
- [Writing Workflows](workflows.md)
- [Functions and Agents](functions-and-agents.md)
- [Tools](tools.md)
