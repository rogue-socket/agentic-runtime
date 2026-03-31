# Gap Analysis: Pain Points vs. Implementation Reality

**Date:** 2026-03-31  
**Scope:** Full source review of `src/agent_runtime/` (~10,200 lines) + 37 test files (~6,700 lines)

---

## Summary

| Category | Count |
|----------|-------|
| **GENUINE** — Real implementation, solves the pain point | 12 |
| **PARTIAL** — Framework exists, feature incomplete | 7 |
| **TODO ONLY** — Claimed/planned, not implemented | 4 |

---

## GENUINE — Fully Implemented

### 1. Deterministic Replay (Pain Point #1: No Reproducibility)
- **File:** `src/agent_runtime/replay.py` (113 lines)
- **Evidence:** `RunReplayer.replay()` loads stored `state_before`/`state_after` from SQLite, reconstructs state step-by-step without calling handlers. `verify_state=True` compares reconstructed vs stored state and raises `ReplayMismatchError`.
- **Assessment:** Not a stub. Working deterministic replay engine.

### 2. Resume From Failure (Pain Point #3: Start From Scratch Tax)
- **File:** `src/agent_runtime/resume.py` (127 lines)
- **Evidence:** `determine_resume_step()` scans execution history, finds the failed step, validates workflow hash matches. `Executor.resume_async()` refuses to resume if the YAML changed since the original run.
- **Assessment:** Solid. Workflow-hash integrity check is a real safety feature.

### 3. Namespaced State (Pain Point #4: Spaghetti State)
- **File:** `src/agent_runtime/state.py` (261 lines)
- **Evidence:** `RuntimeState` enforces `inputs/steps/runtime` namespace structure. Overwrite policies (`warn`/`strict`/`allow`). Reserved keys blocked from step output. Each step writes to `steps.<step_id>` only.
- **Assessment:** Genuine ownership model, not just naming convention.

### 4. Glue Code Elimination (Pain Point #6: Infrastructure Instead of Logic)
- **File:** `src/agent_runtime/core.py` (1037 lines)
- **Evidence:** Executor loop handles type dispatch (agent/function/tool), retry with backoff, state snapshots, atomic SQLite persistence, branch resolution, heartbeat emission, timeout enforcement.
- **Assessment:** This IS the infrastructure code developers would otherwise write per project.

### 5. First-Class Retry (Pain Point #7: Retries as Afterthought)
- **File:** `src/agent_runtime/core.py`, `RetryPolicy` dataclass
- **Evidence:** Per-step `attempts`, `backoff` (fixed/exponential), `initial_delay`. Parsed from YAML, enforced in executor loop with async sleep. `_compute_backoff_delay()` handles the math.
- **Assessment:** First-class, declared in YAML, not bolted on.

### 6. Output Contracts (Pain Point #8: Invisible Failure)
- **File:** `src/agent_runtime/core.py` lines 822-840
- **Evidence:** `output_contract` checks missing AND extra keys against declared contract.
- **Limitation:** Key presence only — no value-level validation (type, enum, regex). See TODO below.

### 7. Declarative YAML Workflows (Pain Point #9: Workflows Buried in Code)
- **File:** `src/agent_runtime/workflow.py`
- **Evidence:** YAML parsing with schema version enforcement, identity extraction, step validation by type, branch rule parsing.
- **Assessment:** Genuine. A new developer reads the YAML, not Python.

### 8. Provider Abstraction (Pain Point #10: Provider Lock-in)
- **File:** `src/agent_runtime/llm/adapters.py` (606 lines)
- **Evidence:** OpenAI, Anthropic, Gemini, and Mock adapters behind common `LLMAdapter` protocol. Each handles its own message format, tool call wire format, and auth. Native function calling across all three providers.
- **Assessment:** Non-trivial, properly implemented. Switching models = one config change.

### 9. Declarative Branching (Pain Point #12: If-Else Routing)
- **File:** `src/agent_runtime/utils.py`, `safe_eval()`
- **Evidence:** AST-restricted expression evaluation (only allows comparisons, boolean ops, attribute access, literals). No arbitrary code execution. Circular branch detection in executor.
- **Assessment:** Real and secure. Branching is YAML, not Python.

### 10. Transaction Safety (Atomic Writes)
- **File:** `src/agent_runtime/storage/sqlite.py` (1308 lines)
- **Evidence:** `SQLiteStorage.transaction()` wraps step+state+status in `BEGIN/COMMIT`. WAL journal mode, foreign keys, schema migration with `ALTER TABLE` backfill.
- **Test coverage:** `test_transaction_safety.py` (314 lines) explicitly tests crash scenarios.
- **Assessment:** Production-grade persistence. Most mature module in the codebase.

### 11. Heartbeats (Pain Point #19: Long-Running Liveness)
- **File:** `src/agent_runtime/core.py`, `_await_with_heartbeat()`
- **Evidence:** Periodically emits `STEP_HEARTBEAT` events during async step execution. Configurable interval.
- **Assessment:** Implemented and functional.

### 12. Secret Redaction (Pain Point #20: Secrets in Traces)
- **File:** `src/agent_runtime/observability.py`
- **Evidence:** Regex-based redaction of API keys, bearer tokens, emails, credit card numbers, credential assignment patterns. Applied to all trace serialization. CLI uses `_redact()` for secret-looking dict keys.
- **Assessment:** Real implementation, not just a TODO.

---

## PARTIAL — Framework Exists, Feature Incomplete

### P1. Structured Observability (Pain Point #2)
- **What works:** `state_before`/`state_after` captured per step. `duration_ms`, `handler_duration_ms`, `agent_trace` persisted. `state-diff` CLI command works. `observability.py` redacts secrets.
- **What's missing:** HTML visualization is a static table dump — no interactive timeline, no clickable step inspection, no state-diff overlay.
- **TODO location:** `src/agent_runtime/visualization/html_renderer.py`

### P2. Cost Visibility (Pain Point #5)
- **What works:** Token usage aggregated per agent turn (`_aggregate_usage`). `LLMClient` enforces `max_requests_per_run`, `max_total_tokens_per_run`, `max_cost_usd_per_run` limits.
- **What's missing:** Cost is NOT persisted on step execution records in practice. No per-step cost calculation in `ai inspect`. Guardrails exist; reporting doesn't.
- **TODO locations:** `src/agent_runtime/agent/strategies.py:200`, `src/agent_runtime/cli.py` (inspect handler)

### P3. Side Effect Idempotency (Pain Point #11)
- **What works:** Resume skips completed steps. `ResumePolicy` has `require_idempotent_tools` and `idempotent_tool_names` to block re-execution of non-idempotent tools.
- **What's missing:** Policy-based ("refuse to retry") not history-based ("this action already happened"). No side-effect recording on step execution records.
- **TODO location:** `src/agent_runtime/resume.py`

### P4. Memory — Episodic (Pain Point #13, partial)
- **What works:** SQLite-backed episodic memory stores/recalls episodes per workflow. `MemoryManager` coordinates hydration before each step.
- **What's missing:** Episodes store only key names (`"repo_url, branch"`), not actual values. Useless for cross-run learning without opening the full state.
- **TODO location:** `src/agent_runtime/memory/episodic.py`

### P5. Memory — Semantic (Pain Point #13, partial)
- **What works:** FTS5 full-text search, tag-based query, exact key lookup. Real SQLite persistence.
- **What's missing:** Facts are only stored when a step explicitly populates `runtime.memory.semantic.store`. Nothing is extracted automatically from agent outputs.
- **TODO location:** `src/agent_runtime/memory/semantic.py`

### P6. Memory — Procedural (Pain Point #13, partial)
- **What works:** SQLite-backed key/value store with read/write protocol.
- **What's missing:** Empty plumbing. No LLM-assisted rule extraction from episodic history. No auto-learning.
- **TODO location:** `src/agent_runtime/memory/procedural.py`

### P7. Testing via Replay (Pain Point #14)
- **What works:** Replay can verify state matches. MockAdapter enables deterministic tests without API calls.
- **What's missing:** No `capture_golden` / `replay_golden` test-fixture workflow. No CLI command to snapshot a run as a test case.
- **TODO location:** `src/agent_runtime/replay.py:42`

---

## TODO ONLY — Not Yet Implemented

### T1. Config Environment Layering (Pain Point #15)
- **File:** `src/agent_runtime/config.py:73`
- **Status:** Comment describes `runtime.prod.yaml` overlays and env-var interpolation. Zero implementation. `load_config()` reads a single file with no layering.

### T2. Cross-Run Rate Limiting (Pain Point #16)
- **File:** `src/agent_runtime/llm/client.py:19`
- **Status:** Per-instance rate limiting works. Concurrent executor instances sharing a throttled request queue is described but not built.

### T3. Fan-Out / Fan-In (Pain Point #18)
- **File:** `src/agent_runtime/core.py:1091`
- **Status:** Detailed 3-step design in comments (`parallel_group`, DAG scheduler, atomic merge). Steps execute strictly sequentially. Zero implementation.

### T4. Workflow-Level Degradation (Pain Point #17, extends per-step `optional`)
- **File:** `src/agent_runtime/memory/base.py` (new TODO)
- **Status:** Per-step `optional: true` + `default_output` works. No workflow-wide circuit breaker, quality threshold, or degradation mode.

---

## TODO Inventory — All `TODO(pain-point)` Markers in Source

| File | Line | Pain Point | Summary |
|------|------|-----------|---------|
| `config.py` | 73 | Config Drift | Environment-aware config layering |
| `core.py` | 172 | Latency Budgets | Workflow-level timeout / step budget |
| `core.py` | 708 | Hallucination Guardrails | Grounding validator hook for agent output |
| `core.py` | 822 | Structured Output Parsing | Value-level schema validation (type/enum/regex) |
| `core.py` | 1091 | Fan-Out/Fan-In | Parallel step execution with DAG scheduler |
| `replay.py` | 39 | Cold-Path Amnesia | Branch-coverage tracking across replays |
| `replay.py` | 42 | Snapshot Testing | `capture_golden`/`replay_golden` test fixtures |
| `resume.py` | (new) | Idempotency Tracking | History-based side-effect recording |
| `cli.py` | (new) | Per-Step Cost Reporting | USD cost calculation in `ai inspect` |
| `llm/client.py` | 19 | Cross-Run Rate Limiting | Shared throttle for concurrent executors |
| `llm/client.py` | 25 | Model Regression Detection | Compare outputs across model versions |
| `agent/strategies.py` | 200 | Cost Accounting | Persist token usage on step records |
| `memory/episodic.py` | (new) | Episodic Memory Depth | Store values, not just key names |
| `memory/semantic.py` | (new) | Auto-Extraction | Extract facts from agent outputs automatically |
| `memory/procedural.py` | (new) | Auto-Learning | Mine episodic history for procedural rules |
| `memory/base.py` | (new) | Workflow-Level Degradation | Circuit breaker + quality threshold |
| `visualization/html_renderer.py` | (new) | Interactive Timeline | Clickable timeline with state-diff overlay |
| `visualization/ascii_renderer.py` | 19 | Aggregate Observability | Cross-run analytics |
| `__init__.py` | 79 | Export/Wire-Into-Product | Clean public API surface |

---

## Prioritized Implementation Recommendations

### Tier 1 — High Impact, Low Effort (close the gap between claim and reality)
1. **Cost Accounting** (`strategies.py` + `cli.py`) — Persist token_usage on step records and compute USD in `ai inspect`. The data is already captured; it just needs to be wired through.
2. **Episodic Memory Depth** (`episodic.py`) — Store truncated input values and step outputs, not just key names. One-line change to `write()`.
3. **Structured Output Schemas** (`core.py`) — Add optional `type`/`enum`/`regex` validation per output key. The contract check is already there; extend it.

### Tier 2 — Medium Impact, Medium Effort (complete the developer experience)
4. **Snapshot Testing** (`replay.py` + `cli.py`) — `ai capture-golden <run_id>` + `ai test-golden`. The replay engine already does the work; it needs a fixture format.
5. **Interactive HTML Visualization** (`html_renderer.py`) — Embed a JS timeline (D3/Mermaid) with clickable steps. High developer-experience payoff.
6. **Config Environment Layering** (`config.py`) — `runtime.yaml` + `runtime.{env}.yaml` overlay + `${ENV_VAR}` interpolation. Standard pattern, well-understood.

### Tier 3 — High Impact, High Effort (roadmap features)
7. **Fan-Out/Fan-In** (`core.py`) — Parallel step execution. Requires DAG scheduler, partial-failure handling, atomic result merge. Significant architectural work.
8. **Semantic Memory Auto-Extraction** (`semantic.py`) — LLM-assisted fact extraction from agent outputs. Requires careful prompt engineering and cost management.
9. **Procedural Memory Auto-Learning** (`procedural.py`) — Mine episodic history for reusable rules. Depends on episodic memory being rich enough first.

---

## Verdict

The **foundations are real and well-built**: execution, persistence, replay, resume, state management, branching, provider abstraction, and transaction safety. These are not stubs or wrappers — they're the kind of infrastructure that takes months to build correctly.

The **gaps are honest**: every missing feature has a `TODO(pain-point)` comment in the exact line of code where it would be implemented. The codebase doesn't pretend features exist that don't.

The **risk** is the distance between the **marketing narrative** (painpoints.md) and the **current state**. Pain points #5 (cost visibility), #11 (idempotency), #13 (memory), and #14 (testing) are described as "solved" in the vision doc but are partially implemented in code. The Tier 1 recommendations above would close the most visible gaps with the least effort.
