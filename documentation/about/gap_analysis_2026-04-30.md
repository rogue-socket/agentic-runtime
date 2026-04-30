# ForrestRun -- Deep Gap Analysis

**Date:** 2026-04-30
**Scope:** Full source review of `src/agent_runtime/` (~12,000 lines) + 40+ test files (~7,500 lines) + new SDK surface (`builder.py`, `defaults.py`, `events.py`, `streaming.py`, `sse.py`)
**Method:** Six parallel deep-research passes covering every gap area with line-level code tracing

---

## Executive Summary

ForrestRun's foundations are production-grade: execution, persistence, replay, resume, state management, branching, provider abstraction, and transaction safety. These are not stubs.

Six gaps remain between the current codebase and the 0.2.0/0.3.0 roadmap targets. This document provides line-level analysis of each, with exact break points, readiness assessments, and implementation paths.

| # | Gap | Impact | Effort | GitHub Issue |
|---|-----|--------|--------|--------------|
| 1 | [Cost accounting pipeline break](#1-cost-accounting-pipeline) | High | Low (~1 day) | #1 |
| 2 | [Async-safe sync wrappers](#2-async-safe-sync-wrappers) | High | Low (~1 day) | #2 |
| 3 | [LLM streaming (5-layer gap)](#3-llm-streaming) | High | High (~3 weeks) | #3 |
| 4 | [Memory subsystem gaps](#4-memory-subsystem) | High | Medium-High | #4 |
| 5 | [CLI + core monolith](#5-cli--core-monolith) | Medium | Medium (~3 days) | #5 |
| 6 | [Multi-agent composition](#6-multi-agent-composition) | High | Very High (~6 weeks) | #6 |

---

## 1. Cost Accounting Pipeline

### Current State

Token usage IS captured and persisted end-to-end. USD cost is calculated in `LLMClient` memory but **never persisted** -- it is lost when the process exits. CLI recalculates cost at display time.

### Data Flow With Break Points

```
Provider API Response
  |
  v
Adapter extracts usage dict
  --> LLMResponse.usage (in-flight)                    [adapters.py:413/666/1014]
  |
  v
LLMClient._record_usage_and_enforce_post_call_limits()
  --> Calculates cost_usd via _estimate_cost_usd()     [client.py:308-330]
  --> Stores in self._run_usage[run_id]["cost_usd"]     [client.py:246-281]
  --> IN-MEMORY ONLY                                    <<< BREAK 1 >>>
  |
  v
Strategy._aggregate_usage(turns)
  --> Sums TOKENS only from turn.llm_response.usage     [strategies.py:248-256]
  --> Ignores LLMClient cost tracking entirely          <<< BREAK 2 >>>
  |
  v
AgentResult.token_usage = aggregated tokens dict        [strategies.py:60-67]
  |
  v
Executor._dispatch_agent()
  --> execution.token_usage = agent_result.token_usage  [core.py:492]
  --> StepExecution has NO cost_usd field                <<< BREAK 3 >>>
  |
  v
Storage.append_step()
  --> Persists token_usage_json column                   [sqlite.py:234]  OK
  --> NO cost_usd column exists                         <<< BREAK 4 >>>
  |
  v
CLI inspect
  --> Loads step.token_usage from storage
  --> Recalculates cost from tokens + pricing config    [cli.py:3480-3526]
  --> _estimate_step_cost_usd() at display time         [cli.py:271-297]
```

### What Is Persisted vs. What Is Lost

| Data | Persisted? | Location |
|------|-----------|----------|
| Token counts per step | YES | `steps.token_usage_json` (SQLite) |
| Model name per step | YES | `steps.model_name` (SQLite) |
| USD cost per request | NO | `LLMClient._run_usage` (in-memory, lost on exit) |
| USD cost per step | NO | Not calculated at step level |
| USD cost per run | NO | Not aggregated |

### Key Code References

| Component | File | Lines |
|-----------|------|-------|
| Cost calculation | `llm/client.py` | 308-330 (`_estimate_cost_usd`) |
| Usage recording | `llm/client.py` | 246-281 (`_record_usage_and_enforce_post_call_limits`) |
| Pricing config lookup | `llm/client.py` | 316-325 (provider/model or wildcard) |
| Token aggregation | `agent/strategies.py` | 248-256 (`_aggregate_usage`) |
| StepExecution model | `core.py` | 191-214 (has `token_usage`, no `cost_usd`) |
| SQLite steps schema | `storage/sqlite.py` | 214-239 (has `token_usage_json`, no `cost_usd`) |
| CLI cost display | `cli.py` | 3480-3526 (recalculates at display time) |

### Adapter Token Extraction

Each adapter extracts usage differently from provider responses:

- **OpenAI** (`adapters.py:413`): `usage=raw.get("usage")` -- `{"prompt_tokens", "completion_tokens", "total_tokens"}`
- **Anthropic** (`adapters.py:666`): `usage=raw.get("usage")` -- `{"input_tokens", "output_tokens"}`
- **Gemini** (`adapters.py:1014`): `usage=raw.get("usageMetadata")` -- `{"promptTokenCount", "candidatesTokenCount", "totalTokenCount"}`
- **Mock** (`adapters.py:93`): Synthetic `{"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}`

### Implementation Path

1. Add `cost_usd: Optional[float] = None` to `StepExecution` dataclass
2. Add `cost_usd` column to SQLite `steps` table
3. Update `storage.append_step()` to persist cost
4. Pass cost from `LLMClient` response through `AgentResult` to executor
5. Add run-level cost aggregation to `Run` model
6. Update CLI `inspect` to display persisted cost

**Effort:** ~1 day. All infrastructure exists; 6 touch points need wiring.

---

## 2. Async-Safe Sync Wrappers

### Current Architecture

Three sync entry points, all identical pattern -- detect running loop, raise `RuntimeError`:

| Entry Point | File | Lines | Pattern |
|-------------|------|-------|---------|
| `run_workflow()` | `__init__.py` | 80-88 | `asyncio.get_running_loop()` -> raise -> `asyncio.run()` |
| `Runtime.run()` | `builder.py` | 96-103 | Same |
| `Executor.run()` | `core.py` | 631-632 | `_ensure_no_running_loop()` at 1240-1251 |

### Sync-to-Async Call Chain

```
User code (script, CLI):
  run_workflow()                          [__init__.py:51]
    --> asyncio.get_running_loop()        [__init__.py:80]  raises (no loop)
    --> asyncio.run(                      [__init__.py:88]
      run_workflow_async()
        --> load_config, build storage, memory, registries, LLM client
        --> Executor(steps, ...).run_async()
          --> __execute_steps_loop()
            --> _dispatch_agent() [async]
            --> _dispatch_function() [sync]
            --> _dispatch_tool() [async]
    )

User code (FastAPI/Jupyter):
  run_workflow()
    --> asyncio.get_running_loop()        SUCCEEDS (loop exists)
    --> RuntimeError("Detected running event loop. Use run_workflow_async()")
    --> NO FALLBACK
```

### The Failure Mode

```python
# FastAPI route handler:
@app.post("/analyze")
async def analyze(req: Request):
    result = run_workflow("workflow.yaml", inputs=req.json())
    # --> RuntimeError: Detected a running event loop.
    #     Use `run_workflow_async()` instead of `run_workflow()`.
```

### Existing TODO

`core.py:1244-1245`:
```
TODO(eng): Provide an opt-in helper to run sync APIs in async contexts by
  dispatching to a dedicated worker thread if we ever need that behavior.
```

### Fix Options (Zero New Dependencies)

**Option A: Worker Thread (Recommended)**
- Spawn `threading.Thread` with `asyncio.new_event_loop()` + `asyncio.run()`
- Join thread, return result or re-raise exception
- Pros: stdlib only, clean loop isolation, deterministic
- Cons: thread overhead (negligible for LLM-bound work)

**Option B: Optional nest_asyncio**
- Detect loop -> try `import nest_asyncio` -> `apply()` -> `asyncio.run()`
- Pros: seamless in Jupyter
- Cons: violates zero-dep principle, safety concerns

**Option C: Status quo + documentation**
- Keep raising, document sync vs async API clearly
- Pros: forces correct usage
- Cons: poor DX, blocks adoption

### Test Coverage

Single test at `test_runtime.py:236-255` verifies the error is raised. No tests for FastAPI/Jupyter scenarios or thread-pool fallback.

**Effort:** ~1 day with worker thread approach.

---

## 3. LLM Streaming

### Current State

The type system, SSE parser, and adapter stream methods are built and tested (72 tests). But the adapter `stream()` methods are **broken at runtime**, and nothing above the adapter layer has streaming support.

### What Exists (Well-Built, Tested)

| Component | File | Lines | Tests |
|-----------|------|-------|-------|
| `StreamChunk` (7 types) + `StreamingLLMResponse` | `llm/streaming.py` | 213 | 28 in `test_streaming_types.py` |
| `SSEStreamParser` (stateful line parser) | `llm/sse.py` | 154 | 31 in `test_sse_parser.py` |
| OpenAI `stream()` + `_openai_parse_event()` | `adapters.py` | 418-564 | 13 in `test_adapter_streaming.py` |
| Anthropic `stream()` + `_anthropic_parse_event()` | `adapters.py` | 671-842 | (shared) |
| Gemini `stream()` + `_gemini_parse_chunks()` | `adapters.py` | 1019-1165 | (shared) |

### Critical Bug: Adapter stream() Is Broken

`_urlopen_with_retry()` (lines 100-121) blocks and returns a parsed JSON dict:

```python
with urllib.request.urlopen(req, timeout=timeout) as resp:
    return json.loads(resp.read().decode("utf-8"))  # returns dict
```

But `stream()` methods call it expecting a context manager:

```python
with _urlopen_with_retry(req, timeout=timeout) as response:  # dict has no __enter__
    for line in response:  # WILL FAIL
```

This raises `AttributeError` at runtime. A separate `_urlopen_streaming()` function is needed that returns the raw `http.client.HTTPResponse` object for line-by-line iteration.

Note: urllib CAN do chunked reads -- `for line in resp:` works on the raw response object. The stdlib supports it.

### Five-Layer Gap

| Layer | File | Lines | Status | Work Needed |
|-------|------|-------|--------|-------------|
| 1. HTTP transport | `adapters.py` | 100-121 | Broken | Create `_urlopen_streaming()` |
| 2. Adapter stream() | `adapters.py` | 418+ | Broken (wrong fn) | Wire to new transport |
| 3. LLMClient | `llm/client.py` | 65-176 | Missing | Add `stream()` method |
| 4. Strategy | `agent/strategies.py` | 489 | Missing | Consume streaming iterator |
| 5. Executor | `core.py` | 449-504 | Missing | Emit stream events via `_emit()` |

### EventCallback System (Ready for Streaming)

The existing event system can carry streaming events without modification:

- `EventCallback = Callable[[str, Dict[str, Any]], None]` at `core.py:54`
- `_emit()` at `core.py:359-373` -- fire-and-forget with exception swallowing
- Could emit `AGENT_STREAM_CHUNK` events with `StreamChunk` payload
- Already supports `AGENT_MODEL_START` / `AGENT_MODEL_COMPLETE` events from strategies

### Strategy Integration Point

```python
# Current path (strategies.py:489):
response = llm_client.call(...)  # blocks until full response

# Streaming path (needed):
if should_stream:
    chunks = []
    async for chunk in llm_client.stream(...):
        _emit_agent_event(context, "AGENT_STREAM_CHUNK", chunk.__dict__)
        chunks.append(chunk)
    response = StreamingLLMResponse.from_chunks(chunks).to_llm_response()
else:
    response = llm_client.call(...)
```

### Risk Areas

1. **urllib blocking I/O vs async**: `for line in resp:` is blocking; may need `asyncio.to_thread()`
2. **Retry + streaming**: Can't retry mid-stream; partial response + error = data loss
3. **Tool call reassembly**: JSON chunks may split at arbitrary byte boundaries
4. **Timeout handling**: `timeout` applies to connection, not per-chunk reads
5. **Memory**: Long streams accumulate chunks -- need backpressure or limits
6. **MockAdapter**: No `stream()` method for testing without API calls

**Effort:** ~15-20 hours across 5 layers. Foundation is solid; main work is transport fix + wiring.

---

## 4. Memory Subsystem

### Architecture Overview

Four tiers with SQLite persistence, deep-merge hydration via `MemoryManager`, and per-step lifecycle:

```
Per Step:
  1. snapshot = state.snapshot()                             [core.py:865]
  2. memory_manager.hydrate_state(snapshot)                  [core.py:870]
       episodic.read()   --> {"episodes": [...]}            under runtime.memory.episodic
       semantic.read()   --> {"fact_count": N, "facts": []} under runtime.memory.semantic
       working.read()    --> {"scratch": {}, "entries": []} under runtime.memory.working
       procedural.read() --> {"rule_key": {...}}            under runtime.memory.procedural
  3. build step input from hydrated snapshot                 [core.py:871-879]
  4. execute step                                            [core.py:899-912]
  5. memory_manager.persist_state(state)                     [core.py:1005]
       episodic.write()   --> stores truncated input/output (512 bytes)
       semantic.write()   --> stores facts from runtime.memory.semantic.store[]
       working.write()    --> appends last step output as sliding-window entry
       procedural.write() --> stores rules from runtime.memory.procedural.store{}
```

### Tier Status

| Tier | Storage | Implementation | Gap |
|------|---------|---------------|-----|
| **Working** | In-process | Scratch (byte budget), sliding window (deque), active task | Dict insertion order fragility (line 84-88) |
| **Episodic** | SQLite | Record/recall per workflow, truncated input/output JSON | 512-byte truncation may lose detail; stores VALUES not just keys (correcting prior gap analysis) |
| **Semantic** | SQLite + FTS5 | CRUD, full-text search (BM25), tag queries | No auto-extraction from agent outputs |
| **Procedural** | SQLite | Key/value store only | Empty shell -- no auto-learning from episodic history |

### Gap 4a: Memory NOT Injected Into Agent Prompts (Critical)

**Impact:** Agents cannot benefit from memory unless developers manually template it.

Strategies receive `AgentContext` with full state including hydrated memory, but **never extract or present memory fields to the LLM**:

- `SingleCallStrategy` (lines 614-637): Only uses `inputs` from pipeline state
- `ReActStrategy` (lines 652-825): Only uses `inputs`, `_iteration`, `_history`
- Neither reads from `context.state["runtime"]["memory"]`

**Current workaround:** Developer must manually add `{{ runtime.memory.semantic.facts }}` to prompt templates in agent YAML. No automatic injection.

**Fix:** Strategies should optionally inject memory context. Could be opt-in per agent definition:
```yaml
agent:
  id: triage_agent
  memory_injection: [episodic, semantic]  # auto-inject these tiers into system prompt
```

### Gap 4b: Semantic Memory -- No Auto-Extraction

`semantic.py:126-133` TODO:
```
TODO(pain-point): Semantic Memory Auto-Extraction - Facts are only stored
  when a step explicitly populates `runtime.memory.semantic.store`.
  Nothing is learned automatically. Add an optional post-step hook that
  uses a lightweight LLM call (or regex heuristics) to extract key facts
  from agent outputs.
```

Facts are stored ONLY via explicit `runtime.memory.semantic.store` payload in step output. Two approaches:
1. Regex heuristics (zero LLM cost, limited quality)
2. Lightweight LLM summarization (higher quality, adds cost + latency)

### Gap 4c: Procedural Memory -- Empty Shell

`procedural.py:110-120` TODO:
```
TODO(pain-point): Procedural Memory Auto-Learning - The original vision:
  mine episodic history for reusable patterns and auto-generate procedural
  rules. Implementation path: (1) After N episodes, run LLM summarization
  over episodic history, (2) store extracted rules, (3) inject matching
  rules during hydration.
```

Currently: SQLite-backed key/value store with upsert on write, full dump on read. No filtering, no context awareness, no auto-learning.

### Test Coverage

| Tier | Tests | Coverage Quality |
|------|-------|-----------------|
| Working | `test_working_memory.py` | Comprehensive (scratch, entries, active task, byte budget, reset) |
| Episodic | `test_episodic_memory.py` | Good (record/recall, filtering, persistence) |
| Semantic | `test_semantic_memory.py` | Good (CRUD, FTS5, tags, tier protocol) |
| Procedural | `test_procedural_memory.py` | Minimal (stub mode only, no SQLite tests) |
| **Cross-tier** | None | No integration tests of full hydration cycle or cross-run memory |

### Key Code References

| Component | File | Lines |
|-----------|------|-------|
| MemoryManager + deep-merge | `memory/base.py` | 44-94 |
| Episodic schema | `memory/episodic.py` | 63-76 |
| Episodic write (truncated JSON) | `memory/episodic.py` | 107-139 |
| Semantic FTS5 search | `memory/semantic.py` | 267-298 |
| Semantic auto-extraction TODO | `memory/semantic.py` | 126-133 |
| Procedural auto-learning TODO | `memory/procedural.py` | 110-120 |
| Hydration in executor | `core.py` | 870 |
| Persist in executor | `core.py` | 1005 |
| Strategy prompt rendering | `agent/strategies.py` | 389-395 |

---

## 5. CLI + Core Monolith

### CLI.py (3,944 lines, 67 helpers, 17 commands)

Natural module boundaries:

| Module | Lines | Commands |
|--------|-------|----------|
| `cli/init.py` | ~1,400 | `init`, `quickstart`, `onboard` |
| `cli/config.py` | ~200 | `config`, provider wizard |
| `cli/run.py` | ~400 | `run`, home screen |
| `cli/inspect.py` | ~500 | `inspect`, `state-diff`, `resume`, `replay` |
| `cli/viz.py` | ~300 | `visualize`, `runs`, `metrics` |
| `cli/test.py` | ~600 | `test` (workflows/agents/functions/tools) |
| `cli/helpers.py` | ~400 | redaction, env, prompting, tarball, cost |
| `cli/__init__.py` | ~100 | `run_cli()` dispatcher, argparse |

Inline template strings (YAML examples, HTML templates) account for ~800 lines and could move to `cli/templates/`.

### Core.py (1,370 lines, 8 subsystems)

Extractable concerns:

| Module | Functions | Lines |
|--------|-----------|-------|
| `dispatch.py` | `_dispatch_agent/function/tool`, `_execute_tool_async` | ~150 |
| `retry.py` | `_compute_backoff_delay`, retry loop | ~50 |
| `branching.py` | `_resolve_next_step`, NextRule eval | ~50 |
| `validation.py` | `_validate_output_schema`, contract checks | ~60 |
| `models.py` | `RunState`, `Run`, `StepExecution`, `StepDefinition`, enums | ~130 |

What stays in core.py: `Executor.__init__()`, `run()`/`run_async()`, `__execute_steps_loop()`, `_emit()`, timeout/heartbeat wrappers.

### Coupling Analysis

```
cli.py  -->  core.py: imports Executor, Run, RunState, StepDefinition, StepStatus
core.py -->  config, storage, memory, agent, tools, state, observability, errors, utils
```

All one-directional. No circular dependencies. Safe to refactor independently.

### Output Contract Validation (Already More Complete Than Documented)

The gap analysis previously noted "key presence only" -- but `_validate_output_schema()` at `core.py:1317-1370` already supports:
- **type**: str/int/float/bool/list/dict (via `_OUTPUT_TYPE_MAP` at 1303-1314)
- **enum**: list of allowed values
- **regex**: `re.fullmatch()` for strings

This duplicates type-checking from `tools/validation.py:16-46`. Could be unified.

**Effort:** ~3 days. CLI split is higher priority (3,944 > 1,370 lines).

---

## 6. Multi-Agent Composition

### Current Agent Execution Flow

```
Executor.__execute_steps_loop()           [core.py:810]
  step_type == "agent"
  --> _dispatch_agent()                   [core.py:449]
    --> AgentRegistry.get(agent_id)       [core.py:467]
    --> AgentExecutor(defn, llm, tools)   [core.py:472]
    --> AgentContext(run_id, step_id, state, emit)  [core.py:473-481]
    --> executor.execute(context)         [core.py:484-490]
      --> resolve_strategy()             [strategies.py:830-843]
      --> strategy.run()                 [strategies.py]
        --> _run_pipeline()              [strategies.py:436-597]
          --> model steps: LLM call + tool dispatch
          --> tool steps: direct tool call
      --> AgentResult(outputs, trace, token_usage)
```

### TODOs in Code

| TODO | File | Lines |
|------|------|-------|
| Multi-agent composition | `core.py` | 1267-1269 |
| Agent pipeline step type | `definition.py` | 57-58 |
| Fan-out/fan-in | `core.py` | 1255-1266 |

### Readiness Assessment

| Component | Ready? | Notes |
|-----------|--------|-------|
| WorkflowRegistry | YES | Resolves by id+version, scans directories |
| AgentRegistry | YES | Full bidirectional lookup |
| Executor loop | PARTIAL | Async-safe, re-entrancy untested |
| Step dispatch | PARTIAL | Can add `_dispatch_workflow()` |
| State namespace | NO | Flat `steps.<step_id>` -- collisions in nested runs |
| Storage schema | NO | No `parent_run_id`, no nesting depth, no execution path |
| Event hierarchy | PARTIAL | Events work but lack nesting context |
| Replay | NO | `RunReplayer` handles single runs only |
| Tests | NO | Zero composition tests or examples |

### Re-Entrancy Analysis

| Concern | Status | Detail |
|---------|--------|--------|
| Event loop | SAFE | `asyncio.run()` not used internally; await within existing loop |
| SQLite connection | NEEDS DESIGN | `_in_transaction` is instance-level; nested calls absorbed implicitly |
| LLM client | SAFE | `_run_usage[run_id]` keyed by run_id -- separate entries for sub-runs |
| Registries | SAFE | Read-only lookup |
| Event callbacks | AT RISK | Single `on_event` with no hierarchy context; nested runs share callback |

### State Isolation Problem

| Concern | Current | Needed |
|---------|---------|--------|
| Output namespace | `steps.<step_id>` (flat) | `steps.<parent_step>.<child_step>` (hierarchical) |
| Input passing | Sub-agent sees entire parent state | Explicit input contract per sub-workflow |
| Run records | No parent-child FK | `parent_run_id` column + `nesting_depth` |
| State versions | Single chain per run | Per-sub-run version chains |
| Resume | Flat step scanning | Recursive sub-run scanning |

### Storage Schema Changes

```sql
ALTER TABLE runs ADD COLUMN parent_run_id TEXT REFERENCES runs(id);
ALTER TABLE runs ADD COLUMN nesting_depth INTEGER DEFAULT 0;
ALTER TABLE runs ADD COLUMN execution_path TEXT;
```

### Proposed YAML Syntax

```yaml
steps:
  - id: prepare
    type: function
    handler: prepare_data
    outputs: [extracted_data]

  - id: analyze
    type: workflow
    workflow: specialist_workflow@v2
    inputs:
      data: steps.prepare.extracted_data
    outputs: [results, metrics]

  - id: summarize
    type: agent
    agent: summarizer
    inputs:
      analysis: steps.analyze.results
```

### Implementation Phases

**Phase 1 -- MVP (~3-4 weeks):** Add `workflow` step type, `_dispatch_workflow()`, `parent_run_id` column, flat output nesting, basic tests.

**Phase 2 -- Production (~2-3 weeks):** Input contracts, nesting depth guard, event hierarchy, replay support, CLI inspect for sub-runs, reference example.

**Phase 3 -- Fan-Out (~future):** Parallel sub-workflow invocation, partial failure, atomic merging, visualization.

---

## New SDK Surface (Context)

Several new files were found in the working tree that address the DX gap. These are relevant context for understanding the gap landscape:

### RuntimeBuilder (`builder.py`, 332 lines)
Fluent API for programmatic embedding. No project directory needed.
```python
runtime = (
    RuntimeBuilder()
    .with_model("openai/gpt-4o")
    .with_db_path(":memory:")
    .with_tool(MyCustomTool())
    .build()
)
run = runtime.run("workflow.yaml", inputs={...})
```

### Defaults (`defaults.py`, 92 lines)
Factory functions: `default_tool_registry()`, `default_memory_manager()`, `default_llm_client()`, `default_agent_registry()`. Called by `RuntimeBuilder.build()`.

### Typed Events (`events.py`, 125 lines)
Dataclasses: `RunStartEvent`, `StepStartEvent`, `StepCompleteEvent`, `StepErrorEvent`, `RunCompleteEvent`. `adapt_typed_callback()` wraps raw `EventCallback` for IDE autocomplete.

### Examples
- `examples/minimal/run.py` (46 lines) -- zero-dep demo with `RuntimeBuilder`, inline YAML, `:memory:` DB
- `examples/shopping_agent/` -- realistic multi-tool agent with custom tools, agent YAML, workflow

These significantly improve the first-10-minutes DX story. The quickstart gap from the March analysis is largely addressed.

---

## Priority Matrix

| Gap | Impact | Effort | Risk | Release Target |
|-----|--------|--------|------|---------------|
| Cost accounting wiring | High (visible to users) | Low (~1 day) | Low | 0.2.0 |
| Async-safe wrappers | High (blocks SDK adoption) | Low (~1 day) | Low | 0.2.0 |
| Memory prompt injection | High (memory is invisible) | Medium (~2 days) | Medium | 0.2.0 |
| CLI monolith split | Medium (maintainability) | Medium (~3 days) | Low | 0.2.0 |
| LLM streaming | High (UX for long calls) | High (~3 weeks) | High | 0.3.0 |
| Semantic auto-extraction | Medium (institutional memory) | Medium (~1 week) | Medium | 0.3.0 |
| Multi-agent composition | High (flagship feature) | Very High (~6 weeks) | High | 0.3.0 |
| Procedural auto-learning | Low (depends on above) | High | High | 0.3.0+ |

---

## Corrections to Prior Gap Analysis

1. **Episodic memory stores values, not just key names.** `episodic.py:124-130` stores full input/output dicts (truncated to 512 bytes via `_truncated_json()`). The March gap analysis claim was incorrect.

2. **Output contract validation already supports type/enum/regex.** `core.py:1317-1370` has `_validate_output_schema()` with full type map, enum checking, and `re.fullmatch()`. The March analysis noted "key presence only" which understated the implementation.

3. **Heartbeats are implemented.** `core.py:_await_with_heartbeat()` emits `STEP_HEARTBEAT` events during async step execution. The March gap listed this as missing.

4. **Secret redaction is implemented.** `observability.py` has regex-based redaction of API keys, bearer tokens, emails, credit cards. CLI uses `_redact()` for secret-looking dict keys.

---

*Produced from six parallel deep-research passes on 2026-04-30.*
