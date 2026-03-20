**Writing Tools (Explained Simply)**

A tool is a Python class that performs an external action — calling an API, reading a file, running a shell command. It wraps that action with metadata and input validation so the runtime can call it safely.

If you are new, remember one sentence:
**A tool is a class with a `name`, a schema, and an `execute()` method.**

---

**When To Use A Tool**

- You need to call an external API or service.
- You need to read or write files.
- You need any side effect outside the workflow state.

If the logic is pure data transformation, use a [function](writing-functions.md). If you need LLM reasoning, use an [agent](writing-agents.md).

---

**Where Tools Live**

Put tool classes in the `tools/` directory. The runtime auto-discovers every class that implements the tool protocol (has `name`, `description`, `input_schema`, and `execute`) and whose class name doesn't start with `_`.

```
tools/
  example_tool.py
  my_api_tool.py
```

One file can contain multiple tool classes.

---

**Anatomy Of A Tool**

```python
from __future__ import annotations

from typing import Any, Dict, Optional
from agent_runtime.tools.base import RuntimeContext, ToolResult

class UppercaseTool:
    name = "tools.uppercase"            # unique tool name
    description = "Uppercases text"     # human-readable description
    input_schema = {                     # JSON Schema for validation
        "type": "object",
        "properties": {
            "text": {"type": "string"},
        },
        "required": ["text"],
    }
    timeout: Optional[float] = None     # optional: execution timeout
    retries: Optional[int] = None       # optional: tool-level retries

    async def execute(
        self, input: Dict[str, Any], context: RuntimeContext
    ) -> ToolResult:
        text = input.get("text", "")
        return ToolResult(
            success=True,
            output={"text": text.upper()},
            error=None,
            metadata=None,
        )
```

| Field | Required | Description |
| :--- | :--- | :--- |
| `name` | Yes | Unique tool id. Workflow steps and agents reference this. |
| `description` | Yes | Short human-readable description. |
| `input_schema` | Yes | JSON Schema that validates tool input. |
| `execute()` | Yes | Async method that performs the action and returns a `ToolResult`. |
| `timeout` | No | Max execution time in seconds. |
| `retries` | No | Tool-level retry count. |

---

**What Happens At Runtime**

1. The runtime reads the workflow step.
2. It finds the tool by `name` in the `tools/` directory.
3. It validates the input dict against `input_schema`.
4. It calls `execute(input, context)`.
5. The `ToolResult.output` dict is stored at `steps.<step_id>` in state. Downstream steps reference its keys directly — e.g. `steps.shout.text`.

---

**The ToolResult**

Every `execute()` must return a `ToolResult`:

```python
ToolResult(
    success=True,           # did it work?
    output={"key": "val"},  # output dict — stored in state
    error=None,             # error message if success=False
    metadata=None,          # optional metadata dict
)
```

On failure, set `success=False` and provide an `error` string. The runtime will handle retry logic if configured.

---

**Input Validation**

`input_schema` uses standard JSON Schema. The runtime validates input before calling `execute()`, catching bad data early with clear error messages.

```python
input_schema = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "format": "uri"},
        "method": {"type": "string", "enum": ["GET", "POST"]},
    },
    "required": ["url"],
}
```

---

**Timeouts And Retries**

Tool-level timeout and retries are set as class attributes:

```python
class SlowApiTool:
    name = "tools.slow_api"
    timeout = 30.0    # seconds
    retries = 2       # retry on failure
    # ...
```

You can also set retry policy at the workflow step level:

```yaml
steps:
  - id: call_api
    type: tool
    tool: tools.slow_api
    inputs:
      url: inputs.api_url
    retry:
      attempts: 3
      backoff: exponential
      initial_delay: 1
```

Step-level retry wraps tool-level retry — they compose.

---

**RuntimeContext**

The `context` parameter gives your tool access to run metadata and storage. Most tools can ignore it, but it's available when you need it.

---

**Using A Tool In A Workflow**

```yaml
steps:
  - id: shout
    type: tool
    tool: tools.uppercase
    inputs:
      text: inputs.message
```

---

**Using A Tool In An Agent**

Tools listed under an agent's `tools:` field can be called during the agent's pipeline:

```yaml
agent:
  id: code_reviewer
  tools:
    - tools.file
    - tools.http
  pipeline:
    - id: fetch
      type: tool
      tool: tools.file
      inputs:
        path: analyze.suggested_file
```

---

**Full Example: Report Builder**

```python
from __future__ import annotations

from typing import Any, Dict, Optional
from agent_runtime.tools.base import RuntimeContext, ToolResult

class ReportBuilderTool:
    name = "tools.report_builder"
    description = "Builds a markdown report from summary and next steps"
    input_schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "priority": {"type": "string"},
            "next_steps": {"type": "string"},
        },
        "required": ["summary", "next_steps"],
    }
    timeout: Optional[float] = None
    retries: Optional[int] = None

    async def execute(
        self, input: Dict[str, Any], context: RuntimeContext
    ) -> ToolResult:
        title = input.get("title", "Report")
        summary = input.get("summary", "")
        priority = input.get("priority", "")
        next_steps = input.get("next_steps", "")
        priority_block = f"\n\n## Priority\n{priority}" if priority else ""
        report = (
            f"# {title}\n\n"
            f"## Summary\n{summary}"
            f"{priority_block}\n\n"
            f"## Next Steps\n{next_steps}\n"
        )
        return ToolResult(
            success=True,
            output={"report": report},
            error=None,
            metadata=None,
        )
```

```yaml
steps:
  - id: build_report
    type: tool
    tool: tools.report_builder
    inputs:
      title: "Incident Report"
      summary: steps.summarize.summary
      priority: steps.classify.severity
      next_steps: steps.diagnose.recommendation
```

---

**Common Mistakes**

- Missing `name` attribute — the runtime can't register the tool without it.
- `execute()` not async — the method must be `async def`.
- Returning a plain dict instead of `ToolResult` — always use the `ToolResult` dataclass.
- Class name starts with `_` — the runtime skips those during discovery.
- Tool name not referenced correctly — workflow YAML must match the `name` attribute exactly.

---

**See Also**

- [Writing Workflows](workflows.md) — How to use tools in a workflow.
- [Writing Agents](writing-agents.md) — LLM-backed reasoning steps.
- [Writing Functions](writing-functions.md) — Deterministic logic steps.
