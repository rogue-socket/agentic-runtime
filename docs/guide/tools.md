**Tools**

Tools are the classes that power `tool` steps. A tool wraps an external action, like calling an API, reading a file, or running a shell command.

**Where Tools Live**

Put tool classes in the `tools/` folder. The runtime auto-discovers them at run time.

**Tool Shape**

```python
from __future__ import annotations

from typing import Any, Dict, Optional
from agent_runtime.tools.base import RuntimeContext, ToolResult

class ExampleTool:
    name = "tools.example"
    description = "Uppercases the provided text"
    input_schema = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
        },
        "required": ["text"],
    }
    timeout: Optional[float] = None
    retries: Optional[int] = None

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

**How The Workflow Uses It**

```yaml
steps:
  - id: shout
    type: tool
    tool: tools.example
    inputs:
      text: inputs.message
```

**Input Validation**

- `input_schema` uses JSON Schema.
- Invalid inputs fail before the tool runs.
- Use this to keep failures clear and early.

**Timeouts And Retries**

- Set `timeout` for slow external calls.
- Set `retries` for transient failures.
- You can also use step-level retry policy in the workflow YAML.

**Tool Context**

`RuntimeContext` includes references to the storage layer and current run metadata. Use it for advanced integrations that need run ids or storage access.
