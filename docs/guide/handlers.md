**Handlers**

Handlers are the functions that power `model` steps. You can think of a handler as a small unit of logic that reads from the workflow state and returns a dictionary of new fields to merge back into state.

**Where Handlers Live**

Put your handler functions in the `handlers/` folder. The runtime auto-discovers them at run time.

**Handler Shape**

```python
from agent_runtime.state import RuntimeState

def summarize_issue(state: RuntimeState) -> dict:
    issue = state.get("issue", "")
    return {"summary": issue[:140]}
```

**How The Workflow Uses It**

```yaml
steps:
  - id: summarize
    type: model
    handler: summarize_issue
    inputs:
      issue: inputs.issue
```

**Return Values**

- Return a plain dictionary.
- Keys become new fields in `steps.<step_id>`.
- You can safely return nested objects; they are stored in JSON.

**Two Discovery Conventions**

1. Zero-config: every public function (not starting with `_`) is registered by name.
2. Explicit: define a `__handlers__` dict to control exported names.

Example explicit registry:

```python
def _internal_helper():
    return "ignored"

def run_analysis(state):
    return {"result": "ok"}

__handlers__ = {
    "analyze": run_analysis,
}
```

**Common Tips**

- Keep handlers pure and deterministic when possible.
- Use `state.get("key")` to read inputs and previous outputs.
- Keep outputs small and structured so they are easy to inspect later.
