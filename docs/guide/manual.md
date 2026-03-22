**Agentic Runtime Manual**

This is the **practical reference** — CLI commands, YAML syntax, code examples, and troubleshooting. For a conceptual overview of the architecture and how the pieces fit together, see the [Knowledge Base](knowledge-base.md).

A workflow is a recipe. Each step reads the current state, does some work, then writes new fields back to the state. The runtime records every step, every state change, and every error, so runs can be inspected, resumed, or replayed later.

**Quickstart**

```bash
mkdir my-agent
cd my-agent
ai quickstart
```

This creates the project structure, configures your LLM provider, and runs the starter workflow.

**Project Structure & Configuration**

```
my-agent/
  agents/           # LLM agent definitions (YAML)
  functions/         # Python functions for function steps
  tools/             # Python tool classes for tool steps
  workflows/         # YAML workflow definitions
  runtime.yaml       # Project-level configuration (e.g. default_model)
  .env               # API keys (not committed)
```

The `runtime.yaml` file is the central nervous system for your environment. Notably, it defines `default_model`, allowing your agent definitions to remain completely provider-agnostic.

**Model Resolution (Expected vs Actual)**
- **Expected (What you want)**: The agent runs automatically on a globally configured model without you needing to specify it in every agent YAML.
- **Actual (What happens under the hood)**: When building the runtime context, if an agent lacks a `model` key, it falls back to the `default_model` in `runtime.yaml`. This guarantees consistent execution and simplifies switching models later.


**Functions (Function Steps)**

Function files live in `functions/` and are referenced from workflow steps via `type: function`.

```python
# functions/my_functions.py

def classify_severity(inputs: dict) -> dict:
    issue = inputs.get("issue", "").lower()
    if "crash" in issue or "down" in issue:
        return {"severity": "critical"}
    return {"severity": "low"}
```

Workflow usage:

```yaml
steps:
  - id: classify
    type: function
    function: my_functions.classify_severity
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
        return ToolResult(
            success=True,
            output={"text": text.upper()},
            error=None,
            metadata=None,
        )
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

By default, the CLI shows compact progress lines. Add `-v` for full structured JSON logs (LLM calls, tool invocations):

```bash
ai run workflows/example.yaml -v
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



**Memory System**

The runtime includes a four-tier memory system that enriches execution context:

- **Working memory** — ephemeral per-run scratch store and sliding context window. Stores key-value pairs with byte budget enforcement, context entries from step outputs, and an active task tracker. Resets at run end.
- **Episodic memory** — SQLite-backed historical run records. Each completed run stores a condensed episode (workflow id, status, inputs summary, outputs summary). On the next run, the runtime hydrates state with past episodes for the same workflow.
- **Semantic memory** — long-term knowledge facts stored in SQLite with FTS5 full-text search. Supports exact key lookup, tag-based queries, and BM25-ranked text search.
- **Procedural memory** — stub (planned: pattern mining from episodic history, rule extraction with confidence scoring).

Memory is hydrated before step execution and persisted after run completion. Each tier’s output is namespaced under `runtime.memory.<tier>` in state.

Configure limits in `runtime.yaml`:

```yaml
memory:
  working:
    max_entries: 50
    max_scratch_bytes: 262144
```

**Lifecycle Hooks and Telemetry**

The executor emits structured events at five lifecycle points:

- `RUN_START` — when the run begins
- `STEP_START` — before each step executes
- `STEP_COMPLETE` — after a step succeeds (includes `duration_ms`)
- `STEP_ERROR` — after a step fails (includes error details)
- `RUN_COMPLETE` — when the run finishes (includes `total_duration_ms`)

Per-step timing captures both total step duration and call-specific latency (`handler_duration_ms` for agent steps, `tool_duration_ms` for tool steps). These metrics are surfaced in CLI progress output and HTML/ASCII visualizations.

**Security And Safety**

- Keep API keys in `.env` or environment variables, not in code.
- Use shell allowlists in `runtime.yaml` if you enable the shell tool.
- Branch conditions use `safe_eval()` with AST validation — only `state` and `len` are permitted; imports, dunder access, lambdas, and comprehensions are blocked.
- The `FileTool` sandboxes all operations to the project root — path traversal (`..`) is rejected.
- Agent import rejects path traversal and symlinks/hardlinks in archives.
- HTTP tool validates URL schemes (http/https only) to prevent SSRF.
- HTML visualization escapes all user content via `html.escape()`.
- LLM credentials are resolved from environment variables at call time — never stored on disk.

If you want deeper reference material, see [Usage](usage.md) and [Writing Workflows](workflows.md).
