**Writing Functions (Explained Simply)**

A function is a plain Python callable that runs deterministic logic. It reads inputs, does some work, and returns a dictionary. No LLM, no side effects — just code.

If you are new, remember one sentence:
**A function step calls a Python function with inputs and stores the returned dict.**

---

**When To Use A Function**

- Parsing, formatting, or transforming data.
- Classification rules or heuristic logic.
- Any operation that should always produce the same output for the same input.

If you need a language model, use an [agent](writing-agents.md). If you need external side effects (APIs, files), use a [tool](writing-tools.md).

---

**Where Functions Live**

Put function files in the `functions/` directory. The runtime resolves them by qualified name.

```
functions/
  stubs.py
  formatters.py
  my_functions.py
```

---

**The Function Signature**

Every function must accept a single `inputs` dict and return a plain dict:

```python
def my_function(inputs: dict) -> dict:
    # read from inputs
    # do deterministic work
    # return a dict
    ...
```

That's it. No base class, no decorator, no registration — just a function.

---

**Minimal Example**

```python
# functions/formatters.py

def format_markdown(inputs: dict) -> dict:
    text = inputs.get("text", "")
    report = f"# Report\n\n{text}\n"
    return {"report": report}
```

```yaml
steps:
  - id: format
    type: function
    function: formatters.format_markdown
    inputs:
      text: steps.summarize.summary
```

---

**What Happens At Runtime**

1. The runtime reads the workflow step.
2. It resolves `formatters.format_markdown` → `functions/formatters.py` → `format_markdown()`.
3. It builds the input dict from the step's `inputs:` mapping.
4. It calls `format_markdown(inputs)`.
5. The returned dict is stored at `steps.format` in state.

---

**Naming Convention**

Reference functions as `<module>.<function_name>`:

| Reference | File | Function |
| :--- | :--- | :--- |
| `stubs.generate_summary` | `functions/stubs.py` | `generate_summary()` |
| `formatters.format_markdown` | `functions/formatters.py` | `format_markdown()` |
| `my_functions.classify` | `functions/my_functions.py` | `classify()` |

---

**More Examples**

**Classification heuristic:**

```python
# functions/stubs.py

def classify_severity(inputs: dict) -> dict:
    issue = inputs.get("issue", "").lower()
    if "crash" in issue or "down" in issue:
        return {"severity": "critical", "reason": "keyword match"}
    return {"severity": "low", "reason": "no critical keywords"}
```

```yaml
steps:
  - id: classify
    type: function
    function: stubs.classify_severity
    inputs:
      issue: inputs.issue
```

**Multi-step pipeline with functions:**

```yaml
steps:
  - id: summarize
    type: agent
    agent: summarizer
    inputs:
      issue: inputs.issue
  - id: classify
    type: function
    function: stubs.classify_severity
    inputs:
      issue: inputs.issue
  - id: format
    type: function
    function: formatters.format_markdown
    inputs:
      text: steps.summarize.summary
```

---

**Testing Functions**

Because functions are pure Python with no framework dependency, they're trivial to unit test:

```python
from functions.stubs import classify_severity

def test_critical():
    result = classify_severity({"issue": "server crash in prod"})
    assert result["severity"] == "critical"

def test_low():
    result = classify_severity({"issue": "button color is off"})
    assert result["severity"] == "low"
```

---

**Common Mistakes**

- Returning something other than a dict — the runtime expects a `dict` and will error otherwise.
- Using `functions/stubs.py` as the reference instead of `stubs.generate_summary` — use module-dot-function format, not file paths.
- Side effects in a function — functions should be pure. If you need to call an API or write a file, use a [tool](writing-tools.md) instead.

---

**See Also**

- [Writing Workflows](workflows.md) — How to use functions in a workflow.
- [Writing Agents](writing-agents.md) — LLM-backed reasoning steps.
- [Writing Tools](writing-tools.md) — External action steps.
