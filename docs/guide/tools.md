**Tools (Explained Simply)**

A tool is a Python class that performs an external action. Use tools when you need to call an API, read a file, or run a shell command.

If you are new, remember one sentence:
**A tool is a class with metadata plus an `execute()` function.**

**When To Use A Tool**

- You need to call an external API.
- You need to touch files or the network.
- You need side effects outside the workflow state.

If you only need to transform data in memory, use a handler instead.

**Where Tools Live**

Put tool classes in the `tools/` folder. The runtime finds them automatically.

**What A Tool Must Provide**

1. `name` — a unique tool id like `tools.example`.
2. `description` — a short human-readable description.
3. `input_schema` — JSON Schema that validates tool input.
4. `execute()` — the async method that does the work.

**Minimal Example**

```python
from __future__ import annotations

from typing import Any, Dict, Optional
from agent_runtime.tools.base import RuntimeContext, ToolResult

class ExampleTool:
    name = "tools.example"          # unique tool name
    description = "Uppercases text" # short description
    input_schema = {                 # JSON Schema
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }
    timeout: Optional[float] = None  # optional timeout
    retries: Optional[int] = None    # optional retries

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

**How The Workflow Uses It**

```yaml
steps:
  - id: shout
    type: tool                 # tool step
    tool: tools.example         # tool name
    inputs:
      text: inputs.message      # input reference
```

**What Happens At Runtime**

1. The runtime reads the workflow.
2. It finds `tools.example` in the `tools/` folder.
3. It validates the input using `input_schema`.
4. It calls `execute(input, context)`.
5. The returned output is stored at `steps.shout` in state.

**Input Validation**

`input_schema` uses JSON Schema. This catches bad inputs early and gives clearer errors.

**Timeouts And Retries**

- `timeout` limits how long the tool can run.
- `retries` is tool-level retry count.
- You can also use step-level retry in the workflow YAML.

**Tool Context**

`RuntimeContext` contains run metadata and access to storage. Most tools can ignore it, but it is there if you need it.

**Tools vs Handlers**

- Tools are for external actions.
- Handlers are for internal logic.

If you are unsure, start with a handler and switch to a tool when you need side effects.
