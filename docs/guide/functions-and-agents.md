**Functions and Agents (Explained Simply)**

The runtime has two step types for running logic: **function** steps and **agent** steps.

- A **function** is a plain Python callable. It reads inputs and returns a dictionary. Use it for deterministic logic — parsing, formatting, classification rules.
- An **agent** is an LLM-backed definition with a reasoning strategy and pipeline. Use it when you need a language model.

If you are new, remember one sentence:
**A function step calls a Python function. An agent step calls an LLM agent.**

---

**Function Steps**

**Where Functions Live**

Put your function files in the `functions/` folder. Reference them by qualified name in workflow YAML.

**What A Function Receives**

The runtime passes an `inputs` dictionary built from the step's `inputs:` mapping.

**What A Function Must Return**

Return a plain dictionary. Those keys become the output of the step.

**Minimal Example**

```python
# functions/my_functions.py

def summarize_issue(inputs: dict) -> dict:
    issue = inputs.get("issue", "")
    return {"summary": issue[:140]}
```

**How The Workflow Uses It**

```yaml
steps:
  - id: summarize
    type: function
    function: my_functions.summarize_issue
    inputs:
      issue: inputs.issue
```

**What Happens At Runtime**

1. The runtime reads the workflow.
2. It resolves `my_functions.summarize_issue` from the `functions/` directory.
3. It builds the input dict from the `inputs:` mapping.
4. It calls `summarize_issue(inputs)`.
5. The returned dict is stored at `steps.summarize` in state.

**Naming Convention**

Reference functions by `<module>.<function_name>`:
- `stubs.generate_summary` → `functions/stubs.py` → `generate_summary()`
- `formatters.format_markdown` → `functions/formatters.py` → `format_markdown()`

---

**Agent Steps**

**Where Agent Definitions Live**

Agent YAML files live in the `agents/` folder. The runtime discovers them automatically.

**What An Agent Definition Contains**

An agent definition specifies: model, system prompt, reasoning strategy, tools, and a pipeline of steps the agent executes internally.

**Minimal Example**

```yaml
# agents/summarizer.yaml
agent:
  id: summarizer
  version: v1
  model: gemini/gemini-2.5-flash
  system: "You are a concise summarizer."
  strategy: single
  pipeline:
    - id: main
      type: model
      prompt: "Summarize this text: {{ inputs.text }}"
```

**How The Workflow Uses It**

```yaml
steps:
  - id: summarize
    type: agent
    agent: summarizer
    inputs:
      text: inputs.issue
```

**Strategies**

- `single` — one LLM call through the pipeline, return result.
- `react` — observe→think→act loop until done or max iterations.
- Custom — provide a dotted import path to your own strategy class.

---

**Functions vs Agents vs Tools**

| | Function | Agent | Tool |
|---|---------|-------|------|
| **Use for** | Deterministic logic | LLM reasoning | External actions |
| **Lives in** | `functions/` | `agents/` | `tools/` |
| **Step type** | `type: function` | `type: agent` | `type: tool` |
| **Example** | Parsing, formatting | Summarizing, reviewing | HTTP calls, file I/O |

If you are unsure, start with a function. If it needs an LLM, make it an agent. If it needs the outside world, make it a tool.
