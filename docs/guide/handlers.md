**Handlers (Explained Simply)**

Think of a handler as a small Python function the runtime calls when it reaches a `model` step. It reads the current state, does some logic, and returns new fields.

If you are new to this, remember one sentence:
**A handler is just a function that reads state and returns a dictionary.**

**Where Handlers Live**

Put your handler functions in the `handlers/` folder. The runtime finds them automatically.

**What A Handler Receives**

The runtime passes a `state` object. You can treat it like a dictionary.

**What A Handler Must Return**

Return a plain dictionary. Those keys become the output of the step.

**Minimal Example**

```python
from agent_runtime.state import RuntimeState

def summarize_issue(state: RuntimeState) -> dict:
    issue = state.get("issue", "")  # read input from state
    return {"summary": issue[:140]}  # return step output fields
```

**How The Workflow Uses It**

```yaml
steps:
  - id: summarize
    type: model                 # model step
    handler: summarize_issue    # function name
    inputs:
      issue: inputs.issue       # pass workflow input into the handler
```

**What Happens At Runtime**

1. The runtime reads the workflow.
2. It finds the `summarize_issue` function in `handlers/`.
3. It builds the input state for the step.
4. It calls `summarize_issue(state)`.
5. The returned dict is stored at `steps.summarize` in state.

**Auto-Discovery Rules**

- If a function is public (does not start with `_`), it is registered automatically.
- If you want custom names, use a `__handlers__` dict.

Example with custom names:

```python
def _internal_helper():
    return "ignored"  # private helpers are not registered

def run_analysis(state):
    return {"result": "ok"}  # exposed output

__handlers__ = {
    "analyze": run_analysis,  # workflow uses handler: analyze
}
```

**Handlers vs Tools**

- Handlers are for *logic* inside your app (classification, parsing, summarizing).
- Tools are for *external actions* (APIs, files, shell commands).

If you are unsure, start with a handler. If it needs the outside world, make it a tool.
