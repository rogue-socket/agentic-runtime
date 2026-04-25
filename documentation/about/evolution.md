# ForrestRun — Conceptual Evolution

**Date:** 2026-03-20

---

## Purpose

This document explains what the runtime became, why, and how the pieces fit together after the refactoring. Read this first if you're trying to understand why things are the way they are.

---

## 1. The central shift: workflows orchestrate agents

The single most important change is the inversion of the containment relationship between workflows and agents.

### Before

The **agent manifest** was the top-level unit. An agent *owned* a workflow and declared everything around it: which handlers to load, which tools to register, which providers to configure, and which environment variables were required. The workflow was subordinate — it ran inside the agent's declared context.

A workflow step did work by dispatching to a **handler**: a Python function discovered from a `handlers/` directory and registered by name. The step type was `type: model`, and the step definition included `handler: some_function_name`. The runtime looked up the handler, called it with the current state, and merged the returned dict back into state.

```
Agent manifest
  └── owns → Workflow
                └── step (type: model)
                      └── dispatches to → Handler (Python function from handlers/)
```

The handler system was the universal dispatch mechanism. Every step that did computation went through a handler. There was no distinction between deterministic logic and LLM reasoning — they were both handlers.

### After

The **workflow** is now the primary orchestration unit. A workflow *contains* steps that call agents, functions, and tools. Agents are components that workflows invoke — not wrappers around workflows.

```
Workflow
  ├── step (type: agent)    → Agent definition (LLM reasoning with strategy + pipeline)
  ├── step (type: function) → Python callable (deterministic logic)
  └── step (type: tool)     → Tool class (external actions)
```

This means:
- A single workflow can compose multiple different agents in sequence, conditionally, or with branching.
- Agents are **reusable building blocks**. The same agent definition can appear in different workflows.
- Agent definitions describe *what the agent can do* (model, strategy, pipeline, tools). The **workflow** decides *when and how* to use it.
- The separation of concerns is explicit: LLM reasoning is an agent step, deterministic transforms are function steps, external side effects are tool steps.

Legacy agent manifest packaging commands are not part of the current CLI surface. Authoring is centered on workflows and agent definitions.

### Why this matters

The handler-centric model conflated orchestration with execution. The agent owned the workflow *and* the execution context, which meant:
- You couldn't easily compose multiple agents in one workflow.
- There was no clean separation between "code that reasons" and "code that transforms data."
- Adding a new agent to a workflow meant creating a new manifest, a new handler, and wiring them together.

The workflow-first model makes composition natural. A triage workflow can call a `summarizer` agent, branch on the result, then call a `reviewer` agent — all in one YAML file, with no handler wiring.

---

## 2. Three step types replaced one

The old runtime had one computational step type: `type: model`, dispatching to a handler function. The new runtime has three, each with a distinct resolution path, execution contract, and purpose.

### Agent steps (`type: agent`)

Agent steps delegate to an **agent definition** — a YAML file in `agents/` that describes an LLM-backed reasoning unit. An agent definition specifies:
- **Model**: which LLM provider and model to use — set once in `runtime.yaml` as `default_model`, inherited by all agents.
- **System prompt**: the agent's persona and instructions.
- **Strategy**: the reasoning pattern — `single` (one pass), `react` (observe→think→act loop), or custom (via dotted import path).
- **Pipeline**: ordered sub-steps the agent executes internally, each with its own prompt template.
- **Tools**: which tools the agent can call during its reasoning loop.

At dispatch time, the executor resolves the `AgentDefinition` from the `AgentRegistry`, creates an `AgentExecutor`, runs the strategy, and captures an `AgentResult` that includes outputs, a full reasoning trace, iteration count, and token usage. The trace is stored in the step execution record for observability.

Agents have their own internal pipelines, which means the LLM-specific concerns (prompt templating, multi-turn reasoning, tool-use loops) are encapsulated inside the agent boundary. The workflow only sees inputs and outputs.

```yaml
# In a workflow:
- id: review
  type: agent
  agent: code_reviewer        # → agents/code_reviewer.yaml
  inputs:
    diff: inputs.pr_diff

# In agents/code_reviewer.yaml:
agent:
  id: code_reviewer
  version: v1
  system: "You are a senior code reviewer."
  strategy:
    type: react
    max_iterations: 5
  tools:
    - tools.file
  pipeline:
    - id: analyze
      type: model
      prompt: "Analyze this code: {{ inputs.diff }}"
    - id: review
      type: model
      prompt: "Write review based on: {{ analyze.text }}"
```

### Function steps (`type: function`)

Function steps call a **plain Python callable** — a function in `functions/` that takes a dict and returns a dict. No LLM, no async, no side effects. Use these for deterministic logic: parsing, formatting, classification, data transformation.

Resolution happens at **parse time** (fail fast). The `function_resolver` imports the module, finds the function, and stores the callable directly on the `StepDefinition`. At execution time, the callable is invoked directly with no framework overhead.

```yaml
- id: classify
  type: function
  function: classifiers.classify_severity   # → functions/classifiers.py → classify_severity()
  inputs:
    issue: inputs.issue
```

```python
# functions/classifiers.py
def classify_severity(inputs: dict) -> dict:
    issue = inputs.get("issue", "").lower()
    if "crash" in issue or "down" in issue:
        return {"severity": "critical"}
    return {"severity": "low"}
```

### Tool steps (`type: tool`)

Tool steps call a **tool class** — a Python class in `tools/` that implements the Tool protocol (`name`, `description`, `input_schema`, `execute()`). Tools handle external actions: HTTP calls, file I/O, shell commands, API integrations.

Tool input is validated against `input_schema` (JSON Schema) before execution. Tools receive a `RuntimeContext` with run metadata and access to the runtime. Execution is async with structured events (`TOOL_START`, `TOOL_SUCCESS`, `TOOL_ERROR`).

```yaml
- id: fetch
  type: tool
  tool: tools.http
  inputs:
    url: inputs.api_endpoint
```

### Workflow `type: model` is removed

Current workflow validation accepts only `type: agent`, `type: function`, and
`type: tool`. There is no workflow-level `type: model` compatibility mode in
the current runtime.

Important distinction: `model` remains valid inside an agent pipeline
(`agents/*.yaml`) where pipeline step types are `model` and `tool`.

---

## 3. The handler system was removed

The legacy handler-dispatch model is not part of the runtime's execution path.
Execution now routes through explicit workflow step types:

- `type: agent` -> agent registry + agent executor
- `type: function` -> function resolver in `functions/`
- `type: tool` -> tool registry

This keeps orchestration declarative and type-specific, instead of routing all
computation through a single handler abstraction.

---

## 4. LLM calls became a first-class subsystem

In the old model, LLM calls were hidden inside handler functions. If a handler called an LLM API, that was the handler's internal concern — the runtime had no visibility into it.

Now LLM communication is a structured subsystem with clear boundaries:

### Provider registry (`llm/registry.py`)

`LLMRegistry` manages providers (OpenAI, Anthropic, Gemini) and their model configurations. Providers are declared in `runtime.yaml` under the `llm:` section. API keys are resolved from environment variables at call time — never stored on disk.

### Adapter pattern (`llm/adapters.py`)

Each provider has an HTTP adapter (`OpenAIAdapter`, `AnthropicAdapter`, `GeminiAdapter`) that normalizes request/response formats. All use stdlib `urllib` — zero additional HTTP dependencies. Adapters now include a shared `_urlopen_with_retry()` helper with:
- 60-second default timeout.
- Exponential backoff retry for transient HTTP errors (429, 500, 502, 503, 504).
- Configurable max retries and initial delay.

### Client routing (`llm/client.py`)

`LLMClient` routes requests to the correct adapter based on provider name, resolves API keys, and logs the call.

### Why this matters

Agent steps use this subsystem internally — the `AgentExecutor` routes through `LLMClient` to make its calls. The subsystem makes LLM calls observable, configurable, and retryable through unified infrastructure. The runtime knows when an LLM call is happening, how long it took, and how many tokens it consumed.

---

## 5. Memory became structured and tiered

The old runtime had no memory model. State existed only within a single run — there was no way for an agent to recall past runs or build up knowledge over time.

The memory subsystem introduces four tiers, each with a distinct lifecycle and storage model:

| Tier | Storage | Lifecycle | Purpose |
|---|---|---|---|
| **Working** | In-memory | Single run | Active scratch space with byte budget, sliding window of context entries, and active task tracking. Cleared at run end. |
| **Episodic** | SQLite | Cross-run | Per-run summaries: workflow id, status, input/output summaries, errors. Gives agents context about what happened in prior runs. |
| **Semantic** | SQLite + FTS5 | Persistent | Long-term knowledge facts with full-text search (BM25 ranking), tags, and metadata. Agents can store and query knowledge that outlives individual runs. |
| **Procedural** | Stub | Future | Learned workflows and playbooks extracted from episodic patterns. Currently a stub with a documented roadmap. |

All tiers implement the `MemoryTier` protocol (`read(context)`, `write(payload)`) and are managed by `MemoryManager`, which hydrates state at run start and persists at run end through namespaced deep-merge into `runtime.memory.<tier>`. This eliminates the shallow-merge state corruption risk that existed in earlier iterations.

---

## 6. Safety and determinism hardened

Several safety boundaries were added or strengthened as the runtime matured:

**Branch expression safety.** `safe_eval` validates branch condition expressions via AST analysis before executing them. The evaluation context allows `state`, `len`, `min`, `max`, `abs`, and string methods (`startswith`, `endswith`, `lower`, `upper`, `strip`). Dunder attribute access (`state.__init__.__globals__`) is blocked. Unary operators and arithmetic are permitted for common predicates.

**Circular branch detection.** The executor tracks visited step IDs during `__execute_steps_loop`. If a step is visited twice, it raises `BranchResolutionError` immediately, preventing infinite loops in misconfigured workflows.

**Workflow integrity lock.** On `ai resume`, the runtime compares the stored workflow hash against the current workflow file. If the workflow has been modified since the original run, it raises `WorkflowIntegrityError` and refuses to resume — preventing silent behavior changes during recovery.

**Tool sandboxing.** `FileTool` validates paths against the project root (`os.sep` check, not just prefix). `ShellTool` applies regex-based allowlist/denylist from `runtime.yaml`. `import_agent` rejects tar archives containing symlinks or path-traversal members.

---

## 7. The project scaffold reflects the step types

The scaffolded project structure now mirrors the three step types directly:

```
my-project/
  agents/         # Agent definitions (YAML) — for type: agent steps
  functions/      # Python functions — for type: function steps
  tools/          # Tool classes — for type: tool steps
  workflows/      # Workflow definitions (YAML) — the orchestration layer
  runtime.yaml    # Runtime configuration (db, providers, limits)
```

The `handlers/` directory is gone. There is a one-to-one correspondence between directory and step type. This makes the mental model concrete: if you need LLM reasoning, you write a file in `agents/`. If you need deterministic logic, you write a file in `functions/`. If you need external actions, you write a file in `tools/`. The workflow composes them.

---

## 8. Agent definitions vs agent manifests

The codebase distinguishes current authoring primitives from older manifest concepts:

**Agent definitions** (current, primary) live in `agents/*.yaml` and describe a single LLM-backed reasoning unit: system prompt, strategy, pipeline, tools. They are referenced from workflow steps via `type: agent`. They are the building blocks of workflows.

**Agent manifests** are a legacy packaging concept. Current runtime flows focus on
workflows + `agents/*.yaml`. The CLI provides `ai export` and `ai import` for
portable project bundles (not agent-level manifests). There is no `ai validate`
command.

The difference: an agent definition says "I am a code reviewer that uses Gemini
with a react strategy." Runtime execution composes these definitions into
workflows.

---

## 9. Observability became structural

The runtime now emits structured lifecycle events at five points: `RUN_START`, `STEP_START`, `STEP_COMPLETE`, `STEP_ERROR`, `RUN_COMPLETE`. Each event carries typed payload (run ID, step ID, step type, duration, error details). This is wired via an optional `EventCallback` passed to the executor.

Per-step timing captures both total step duration and call-specific latency (`handler_duration_ms` for model steps, `tool_duration_ms` for tool steps). Agent steps capture reasoning traces (iterations, tool calls, token usage) in `StepExecution.agent_trace`.

The CLI has primary commands covering the full operate→debug→recover loop:
- **Run**: `ai run`, `ai quickstart`, `ai onboard`, `ai config`
- **Observe**: `ai inspect`, `ai state-diff`, `ai visualize`
- **Recover**: `ai resume`, `ai replay`
- **Discover**: `ai list`, `ai runs`
- **Bootstrap**: `ai init`

---

## 10. What remains

The following are documented roadmap items, not current capabilities:

- **LLM token streaming**: adapters are synchronous; chunked response parsing is the next UX improvement.
- **Richer branch expression language**: currently limited to `state` and `len`; string methods, membership tests, and math helpers are planned.
- **LLM quickstart scaffold**: `ai init` still generates stub functions rather than a working LLM workflow out of the box.
- **DAG / parallel execution**: steps execute sequentially; a DAG scheduler for independent parallel steps is planned.
- **Multi-agent composition**: one workflow cannot currently invoke another workflow or delegate to a sub-workflow.
- **Procedural memory**: the stub exists with a documented extraction design; awaiting episodic+semantic maturity.
- **Async embedding**: `asyncio.run()` in sync wrappers fails inside existing event loops (FastAPI, Jupyter).

Each of these has a code-level follow-up marker or a gap document entry pointing to the specific files involved.

---

*This document describes the state of the codebase as of 2026-03-20.*
