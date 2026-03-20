**Writing Agents (Explained Simply)**

An agent is an LLM-backed reasoning unit. It wraps a model, a system prompt, a strategy, and a pipeline into a reusable definition that workflow steps can call.

If you are new, remember one sentence:
**An agent is a YAML file that tells the runtime which model to call and how.**

---

**When To Use An Agent**

- You need a language model to reason, summarize, review, or generate.
- The output is open-ended and cannot be expressed as deterministic code.

If the logic is deterministic (parsing, formatting, lookups), use a [function](writing-functions.md) instead. If you need external side effects (APIs, files), use a [tool](writing-tools.md).

---

**Where Agents Live**

Agent definitions are YAML files in the `agents/` directory. The runtime discovers them automatically by scanning for files with an `agent:` top-level key.

```
agents/
  summarizer.yaml
  code_reviewer.yaml
```

---

**Anatomy Of An Agent Definition**

```yaml
agent:
  id: summarizer                    # unique agent id
  version: v1                       # version tag
  description: "Summarizes issues"  # human-readable description
  model: gemini/gemini-2.5-flash    # LLM provider/model
  system: "You are a concise summarizer."  # system prompt
  strategy: single                  # reasoning strategy
  tools:                            # tools the agent can use
    - tools.echo
  temperature: 0.3                  # LLM temperature
  max_tokens: 2048                  # max response tokens
  pipeline:                         # ordered pipeline steps
    - id: main
      type: model
      prompt: |
        Summarize the following issue in 2-3 sentences.
        Issue: {{ inputs.issue }}
```

| Field | Required | Description |
| :--- | :--- | :--- |
| `id` | Yes | Unique identifier. Workflow steps reference this. |
| `version` | Yes | Version tag (e.g. `v1`, `v2`). |
| `model` | Yes | LLM model in `provider/model` format. |
| `system` | No | System prompt string, or a `prompts.<id>` reference. |
| `strategy` | Yes | Reasoning strategy: `single`, `react`, or custom. |
| `tools` | No | List of tool names the agent is allowed to call. |
| `temperature` | No | LLM sampling temperature. |
| `max_tokens` | No | Maximum response tokens. |
| `pipeline` | Yes | Ordered list of pipeline steps. |

---

**Strategies**

::::tabs
:::tab Single
One LLM call through the pipeline, return the result. Use this for straightforward tasks like summarization or classification.

```yaml
strategy: single
```
:::
:::tab ReAct
An observe → think → act loop. The agent can call tools between reasoning steps, iterating until it reaches a final answer or hits `max_iterations`.

```yaml
strategy:
  type: react
  max_iterations: 5
```
:::
:::tab Custom
Provide a dotted import path to your own strategy class.

```yaml
strategy: my_module.MyCustomStrategy
```
:::
::::

---

**Pipeline Steps**

The pipeline is the agent's internal execution plan. Each pipeline step has an `id` and a `type`.

| Type | What It Does |
| :--- | :--- |
| `model` | Sends a prompt to the LLM and stores the response. |
| `tool` | Calls one of the agent's registered tools. |

Pipeline steps can reference each other using `{{ step_id.field }}` template syntax:

```yaml
pipeline:
  - id: analyze
    type: model
    prompt: "Analyze this diff:\n\n{{ inputs.diff }}"
  - id: review
    type: model
    prompt: |
      Based on your analysis, write a code review.
      Analysis: {{ analyze.text }}
```

---

**System Prompts**

You can inline the system prompt or reference a versioned prompt block defined in the same file:

```yaml
agent:
  id: code_reviewer
  system: prompts.code_review_system@v2
  # ...
  prompts:
    - id: code_review_system
      version: v1
      text: "You are a code reviewer. Be concise."
    - id: code_review_system
      version: v2
      text: |
        You are a senior code reviewer. For each issue found, specify:
        - Location: file and line
        - Severity: critical, warning, or info
        - Category: bug, security, performance, or style
        - Fix suggestion: a concrete recommendation
```

---

**Giving Tools To An Agent**

List tool names under `tools:`. The agent can call them during pipeline execution (especially useful with the `react` strategy).

```yaml
agent:
  id: code_reviewer
  tools:
    - tools.file
    - tools.http
  strategy:
    type: react
    max_iterations: 5
```

---

**Using An Agent In A Workflow**

```yaml
steps:
  - id: summarize
    type: agent
    agent: summarizer
    inputs:
      issue: inputs.issue
```

The runtime resolves `summarizer` → `agents/summarizer.yaml`, builds the input dict, runs the pipeline, and stores the output at `steps.summarize` in state.

---

**Full Example: Code Reviewer Agent**

```yaml
agent:
  id: code_reviewer
  version: v1
  description: "Reviews code diffs for bugs, security, and style"
  model: gemini/gemini-2.5-flash
  system: prompts.code_review_system@v2
  tools:
    - tools.file
    - tools.http
  strategy:
    type: react
    max_iterations: 5
  temperature: 0.2
  max_tokens: 4096
  pipeline:
    - id: analyze
      type: model
      prompt: "Analyze this code diff:\n\n{{ inputs.diff }}"
    - id: fetch_context
      type: tool
      tool: tools.file
      inputs:
        path: analyze.suggested_file
    - id: review
      type: model
      prompt: |
        Based on your analysis and the file context, write a complete review.
        Analysis: {{ analyze.text }}
        File context: {{ fetch_context }}
  prompts:
    - id: code_review_system
      version: v2
      text: |
        You are a senior code reviewer. For each issue found, specify:
        - Location, Severity, Category, and Fix suggestion.
```

---

**Common Mistakes**

- Agent `id` doesn't match what the workflow references — double-check both sides.
- Forgot `pipeline` — every agent needs at least one pipeline step.
- Used a tool in the pipeline that isn't listed in `tools:` — the runtime will reject it.
- `react` strategy without `max_iterations` — it will default, but set it explicitly to avoid runaway loops.

---

**See Also**

- [Writing Workflows](workflows.md) — How to orchestrate agents in a workflow.
- [Writing Functions](writing-functions.md) — Deterministic logic steps.
- [Writing Tools](writing-tools.md) — External action steps.
