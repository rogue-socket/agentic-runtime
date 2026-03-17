# Architecture Decision Log

This file records significant architectural and technical decisions made during development. Each entry follows a structured format for future reference.

---

## Template

```
## ADR-NNN: <Title>

**Date:** YYYY-MM-DD
**Status:** Accepted | Superseded | Deprecated

### Decision
What was decided.

### Context
What problem or question prompted this decision.

### Reasoning
Why this option was chosen.

### Alternatives Considered
Other approaches that were evaluated and why they were rejected.

### Implications
Consequences, trade-offs, or follow-up work resulting from this decision.
```

---

## ADR-001: Namespaced State Model

**Date:** 2026-03-16 (inferred from codebase)
**Status:** Accepted

### Decision
Runtime state is structured as `{ inputs: {}, steps: {}, runtime: {} }` with each step's output written under `steps.<step_id>`.

### Context
Steps need to read each other's outputs and write their own. Flat dicts risk key collisions between steps or accidental overwrites of input data.

### Reasoning
Namespacing prevents cross-step key collisions, preserves output ownership per step, and makes branch analysis and replay tractable. Dot-path access (`steps.classify.severity`) provides a clear, auditable data lineage.

### Alternatives Considered
- **Flat dict:** Simpler but collision-prone and impossible to attribute outputs to steps.
- **Per-step isolated state:** Safer but requires explicit piping of every value between steps.

### Implications
- All state access goes through `RuntimeState` with dot-path API.
- Step input mappings explicitly declare reads from state paths.
- Output contracts enforce what a step is allowed to write.

---

## ADR-002: Plugin Registry Pattern

**Date:** 2026-03-16 (inferred from codebase)
**Status:** Accepted

### Decision
All extensible subsystems (handlers, tools, LLM providers, workflows) use name→object registry maps with `register()` / `get()` APIs.

### Context
The runtime needs to support built-in functionality and user-provided extensions (custom handlers, tools, LLM providers) without requiring code changes to core modules.

### Reasoning
Registries decouple definition from usage. YAML workflows reference handlers/tools by name; the registry resolves names to implementations at startup. Auto-discovery from directories (`handlers/`, `tools/`) makes registration zero-config for users.

### Alternatives Considered
- **Direct imports:** Tight coupling, no user extensibility.
- **Entry points / plugin system:** Too heavy for the current scope; pyproject.toml doesn't exist yet.

### Implications
- Four registries exist: `StepHandlerRegistry`, `ToolRegistry`, `LLMRegistry`, `WorkflowRegistry`.
- CLI bootstrap initializes all registries before execution.
- Name conflicts between built-in and discovered items need clear precedence rules.

---

## ADR-003: Persistent Connection with Explicit Transaction Management

**Date:** 2026-03-17
**Status:** Accepted

### Decision
`SQLiteStorage` uses a single persistent `sqlite3.Connection` with explicit `BEGIN`/`COMMIT`/`ROLLBACK` transaction management (autocommit mode via `isolation_level=None`). The `Storage` ABC exposes a `transaction()` context manager for callers to group writes atomically.

### Context
The original implementation created a new `sqlite3.Connection` per storage method call. Step records (`append_step`) and state versions (`save_state`) were persisted in separate calls with separate connections. A crash between the two calls would leave the database in an inconsistent state: a step record without a matching state version. Resume/replay logic assumes these are always consistent.

### Reasoning
1. **Single connection** eliminates the root cause — multiple operations can share one transaction.
2. **Explicit transaction management** (`isolation_level=None`) gives the caller full control over commit boundaries instead of relying on Python's implicit transaction behavior.
3. **`transaction()` context manager on the ABC** keeps the interface backend-agnostic. The default is a no-op pass-through; SQLiteStorage overrides with real BEGIN/COMMIT/ROLLBACK. Future PostgresStorage can use its own transaction mechanism.
4. **WAL journal mode** improves crash resilience and allows concurrent readers during writes.
5. **Reentrant nesting** (inner `transaction()` absorbed by outer) keeps the API simple — callers don't need to track whether they're already in a transaction.
6. **Backward compatibility** — individual operations auto-commit when called outside a `transaction()` block, so existing callers (tests, CLI) don't break.

### Alternatives Considered
- **Connection pool:** Overkill for SQLite (single-writer constraint). Better suited for PostgreSQL backend.
- **Savepoints for nested transactions:** Adds complexity without current need. Left as a TODO for future.
- **Batch API (persist_step_and_state):** Would bundle the two operations into one method. Rejected because it's less flexible — other callers might need different groupings.
- **Keep per-call connections, add a "batch" method:** Doesn't solve the fundamental problem — the batch method would still need a shared connection internally.

### Implications
- `SQLiteStorage.__init__` opens a persistent connection; callers should call `close()` when done (or let GC handle it).
- A `threading.Lock` serializes all connection access — safe for multi-threaded callers but not concurrent writers.
- The executor wraps run initialization and per-step persistence in `with self.storage.transaction():`.
- Future backends (Postgres, DynamoDB) must implement `transaction()` or inherit the no-op default.
- TODO: Add SAVEPOINT support if nested independent rollback is ever needed.

---

## ADR-003: stdlib urllib Over HTTP Client Libraries

**Date:** 2026-03-16 (inferred from codebase)
**Status:** Accepted

### Decision
LLM adapters (OpenAI, Anthropic) use Python's stdlib `urllib` for HTTP requests instead of `requests`, `httpx`, or provider SDKs.

### Context
The runtime targets minimal dependencies. Adding `requests` or `openai` SDK increases install footprint and version conflict risk.

### Reasoning
The LLM API surface is small (POST JSON, read JSON response). stdlib `urllib` handles this without adding dependencies. Keeps `requirements.txt` to three packages (PyYAML, pytest, typing-extensions).

### Alternatives Considered
- **`requests`:** More ergonomic but adds a dependency tree.
- **`httpx`:** Async-native but heavyweight for simple POST calls.
- **Provider SDKs (`openai`, `anthropic`):** Version coupling, transitive dependencies, harder to test.

### Implications
- Adapters handle raw HTTP directly (headers, JSON encoding, error parsing).
- No automatic retry/backoff from HTTP libraries — must be handled at the executor level.
- Streaming support will require manual chunked-response parsing.

---

## ADR-004: Workflow Content Hashing for Resume Safety

**Date:** 2026-03-16 (inferred from codebase)
**Status:** Accepted

### Decision
Each run stores a SHA-256 hash of the workflow YAML. Resume is blocked if the current workflow hash doesn't match the stored hash.

### Context
Resuming a failed run with a modified workflow could produce inconsistent state — steps may have changed, been reordered, or removed.

### Reasoning
Content hashing provides a simple integrity check. If the workflow changed, the developer must start a new run rather than risk corrupting a partially-completed one.

### Alternatives Considered
- **No check:** Fast but dangerous — silent state corruption on workflow edits.
- **Structural diff:** More granular (allow safe changes) but complex to implement correctly.

### Implications
- Workflow YAML is stored verbatim in the run record (`workflow_yaml` field).
- Any whitespace or comment change in the YAML file blocks resume.
- Developers who want to fix a handler bug and resume must ensure the YAML itself hasn't changed.

---

## ADR-005: AST-Validated Safe Expression Evaluation

**Date:** 2026-03-16 (inferred from codebase)
**Status:** Accepted

### Decision
Branch `when` conditions are evaluated via `safe_eval()` which parses the expression into an AST, validates allowed node types, and evaluates with a restricted namespace (`state`, `len` only).

### Context
Branch rules need conditional logic (`when: "state.inputs.severity == 'critical'"`). Using Python's `eval()` directly would expose arbitrary code execution from workflow YAML files.

### Reasoning
AST validation constrains expressions to comparisons, boolean logic, attribute access (excluding dunders), and `len()`. This covers realistic branch conditions while preventing code injection.

### Alternatives Considered
- **Raw `eval()`:** Trivial code injection vector.
- **Custom expression language:** Safer but requires a parser/interpreter — over-engineering for the current need.
- **Simple string matching:** Too limited for real branch conditions.

### Implications
- Dunder attribute access (`__init__`, `__globals__`) is blocked.
- Only `state` and `len` are in the eval namespace.
- Complex expressions (function calls, imports, lambdas) are rejected at parse time.

---

## ADR-006: Namespaced Memory Tier Hydration

**Date:** 2026-03-17
**Status:** Accepted

### Decision
Each memory tier writes exclusively to `runtime.memory.<tier_name>` during state hydration, using deep-merge instead of `dict.update` on the top-level state dict.

### Context
The original `MemoryManager.hydrate_state()` called `dict.update()` with each tier's `read()` output directly on the state dict. If a tier returned keys like `inputs` or `steps`, they would silently overwrite critical namespaces, corrupting runtime state.

### Reasoning
Namespacing each tier's output under `runtime.memory.<tier>` makes it impossible for memory data to collide with `inputs`, `steps`, or other `runtime` sub-namespaces. Deep-merge (recursive dict merge) preserves existing state while layering in memory data.

### Alternatives Considered
- **Validate tier output keys:** Reject if they contain reserved names — fragile, requires maintenance.
- **Flat merge with prefix:** `memory_working_key` style — pollutes the top-level namespace.

### Implications
- Handlers/workflows access memory data via `state.runtime.memory.working.*`, `state.runtime.memory.semantic.*`, etc.
- `_deep_merge` helper is a simple recursive dict union; list values are replaced, not concatenated.
- Each tier is independent — one tier's failure doesn't affect others.

---

## ADR-007: Protocol-Driven Memory Tier Interface

**Date:** 2026-03-17
**Status:** Accepted

### Decision
Memory tiers implement `read(state) -> dict` and `write(state)` methods. `read()` inspects state for retrieval directives and returns data to hydrate. `write()` inspects state for persistence directives and stores data.

### Context
Memory tiers need to interact with workflow state without coupling to specific workflow YAML structures. Each tier has different read/write semantics (e.g., semantic memory searches by query, working memory captures step output).

### Reasoning
Convention-based keys (e.g., `runtime.memory.semantic.query`, `runtime.memory.semantic.store`) let workflows opt in to memory operations declaratively. Tiers remain self-contained — they read their namespace and act on what they find.

### Alternatives Considered
- **Explicit API calls from handlers:** More control but couples handlers to specific memory implementations.
- **Global event bus:** Over-engineered for the current scope.

### Implications
- Workflows that don't set the convention keys get no memory interaction (safe default).
- Semantic memory checks `runtime.memory.semantic.query` for search and `runtime.memory.semantic.store` for fact persistence.
- Working memory captures latest step output automatically — no explicit directive needed.

---

## ADR-008: Lifecycle Event Callback System

**Date:** 2026-03-17
**Status:** Accepted

### Decision
The Executor accepts an optional `on_event: EventCallback` callable (`Callable[[str, Dict[str, Any]], None]`) and emits structured events at five lifecycle points: `RUN_START`, `STEP_START`, `STEP_COMPLETE`, `STEP_ERROR`, `RUN_COMPLETE`.

### Context
External consumers (dashboards, CI pipelines, SDK users) need visibility into execution progress without polling storage or parsing logs.

### Reasoning
A single callback function is the simplest possible extension point. It avoids the complexity of an event bus, pub/sub system, or observer pattern while still enabling all common use cases (logging, metrics, progress bars, webhook forwarding).

### Alternatives Considered
- **Event bus / pub-sub:** More flexible but adds infrastructure and complexity for a currently single-consumer use case.
- **Structured logging only:** Doesn't support programmatic consumers — they'd need to parse log output.
- **Progress callback with percentage:** Too narrow — doesn't convey step identity, errors, or timing.

### Implications
- `on_event` can be set at `Executor.__init__` time or overridden per `run_async()` call.
- Event payloads include `run_id`, `step_id` (when applicable), `status`, `error` (on failure).
- Future: streaming LLM tokens could emit `LLM_TOKEN` events through same mechanism.
- SDK's `run_workflow()` passes `on_event` directly to the Executor.

---

## ADR-009: SDK Convenience Functions Over Class-Based API

**Date:** 2026-03-17
**Status:** Accepted

### Decision
The primary SDK surface is two module-level functions: `run_workflow(workflow_path, inputs, ...)` (sync) and `run_workflow_async(...)` (async). These handle all subsystem construction internally.

### Context
Embedding the runtime programmatically required constructing `RuntimeConfig`, `SQLiteStorage`, `MemoryManager`, `ToolRegistry`, `StepHandlerRegistry`, `Executor`, and calling `run_async()` — 20+ lines of boilerplate.

### Reasoning
A single function call with sensible defaults covers the 80% use case (run a workflow file with some inputs). Advanced users can still construct subsystems manually for full control. The sync wrapper uses `asyncio.run()` for callers without an event loop.

### Alternatives Considered
- **Builder pattern:** `Runtime().with_config(...).with_tools(...).run()` — more discoverable but more code to maintain.
- **Class-based `Runtime` object:** Stateful, harder to reason about lifecycle, encourages misuse (reuse across runs).

### Implications
- `run_workflow()` returns a `Run` object — callers can inspect `run.status`, `run.steps`, etc.
- All optional params (`config_path`, `on_error`, `on_event`) have `None` defaults.
- Sync version cannot be called from within an existing async context (standard `asyncio.run()` limitation).

---

## ADR-010: Procedural Memory — Learning Across Runs

**Date:** 2026-03-17
**Status:** Proposed

### Decision
Implement procedural memory as a tier that learns *how* to do things by surfacing execution patterns across historical runs. The runtime owns the execution history and is uniquely positioned to extract reusable strategies, success/failure patterns, and optimized step sequences.

### Context
Semantic memory stores *what* the agent knows (facts, documents). Episodic memory stores *what happened* (past interactions, run logs). Neither captures *how* — the procedural knowledge of which approaches work, which tool sequences succeed, and which parameter choices lead to better outcomes. Agents today start from scratch on every run, even when they've solved similar problems before.

### Reasoning
The "runtime" framing pays off here: because the runtime owns durable run records with full state evolution, it can mine historical executions for patterns. A procedural memory tier can:
- Identify recurring step sequences that succeed vs. fail
- Surface tool-parameter combinations that correlate with good outcomes
- Recommend execution strategies based on input similarity to past runs
- Enable agents that genuinely improve across invocations

This is where the architecture's investment in deterministic state persistence, step-level records, and namespaced outputs becomes a strategic advantage — no other agent framework captures enough execution detail to learn from.

### Implications
- Requires episodic + semantic tiers as prerequisites (both now implemented).
- Initial implementation can use heuristics over run history; later versions can use embeddings.
- Must respect run isolation — procedural memory informs but never mutates another run's state.
- Privacy/safety: learned procedures must be auditable and purgeable.
- Opens the door to "meta-agents" that optimize workflow definitions based on historical performance.

---

## ADR-011: Multi-Agent Composition via Sub-Workflow Steps

**Date:** 2026-03-17
**Status:** Proposed

### Decision
Support multi-agent composition by allowing a workflow step to invoke another workflow (sub-workflow). A child run's output becomes the step output in the parent run, using the existing namespaced state model and durable run records.

### Context
Real-world agent systems are not monolithic. A code review agent might delegate to a security-scan agent, a style-check agent, and a test-coverage agent. Today, this requires external orchestration — the runtime can only execute flat step sequences within a single workflow.

### Reasoning
The existing architecture already supports this structurally:
- **Namespaced state** (`steps.<step_id>`) means a sub-workflow's output naturally maps to a parent step's output namespace with no collision risk.
- **Durable run records** mean child runs are independently inspectable, resumable, and replayable — a child failure doesn't corrupt the parent's state.
- **The registry pattern** makes composition natural: `WorkflowRegistry` resolves workflow names, so a step can reference another workflow by ID just like it references a tool or handler by name.
- **Agent packaging** (manifests, tar archives) means sub-workflows can be distributed as dependencies — agent-as-library.

A new step type (`type: workflow` or `type: agent`) would invoke a child workflow, pass mapped inputs, and capture the child run's terminal output as step output.

### Alternatives Considered
- **External orchestration:** Push composition out of the runtime. Simpler internally but loses state tracking, resume, and replay guarantees across the composition boundary.
- **Inline step merging:** Flatten the child workflow's steps into the parent. Simpler state model but loses independent run identity, complicates resume, and prevents distributing agents as packages.

### Implications
- Child runs need a `parent_run_id` field for lineage tracking.
- Parent step blocks until child run reaches terminal state (sequential composition first; parallel composition later).
- Error propagation policy needed: does a child `FAILED` fail the parent step, or can the parent branch on it?
- Storage must support querying run trees (parent → children).
- Agent packaging becomes more valuable: import an agent, reference it as a sub-workflow step.

---

## ADR-012: Agent Packaging as Distributable Artifacts

**Date:** 2026-03-17
**Status:** Proposed

### Decision
Push the agent packaging story (manifests, tar archives, `import_agent`) toward a full distributable model: agents as portable, versioned artifacts that can be published, imported, and composed as dependencies.

### Context
The runtime already supports agent manifests (`manifest.yaml`), tar archive packaging (`packaging.py`), and importing agents with security validation (symlink/traversal rejection). This positions agents as something beyond local scripts — they can be shared, archived, and distributed. But the current model stops at file-level packaging.

### Reasoning
If agents are portable artifacts with versioned identities, the ecosystem unlocks several capabilities:
- **Agent registries:** A central or private registry (like PyPI or Docker Hub, but for agents) where teams publish and discover agent packages.
- **Versioned agent packages:** Semantic versioning for agent definitions. Pin agent dependencies the way you pin library versions.
- **Agent-as-dependency:** A workflow can declare that it requires `security-scanner@2.1` and `style-checker@1.0`. The runtime resolves and loads them at startup.
- **Reproducibility:** A packaged agent bundles its workflow YAML, tool definitions, provider config, and version metadata — everything needed to reproduce a run.

This is a real differentiator. No agent framework today treats agents as first-class distributable artifacts with dependency management.

### Implications
- Manifest schema needs a `dependencies` field for declaring required sub-agents.
- Resolution strategy: local-first (check `agents/` directory), then registry lookup.
- Integrity: package signing or hash verification for registry-sourced agents.
- Version conflict resolution: what happens when two dependencies require different versions of the same sub-agent?
- The `import_agent` security model (symlink rejection, path validation) becomes critical infrastructure, not just a safety check.

---

## ADR-013: Observability as First-Class Infrastructure

**Date:** 2026-03-17
**Status:** Proposed

### Decision
Treat observability as a first-class concern, not an afterthought. Every run should be a trace with spans, compatible with OpenTelemetry and standard observability tooling. This makes the runtime CI/CD-native — agents can run in pipelines with the same monitoring expectations as microservices.

### Context
The runtime already has the building blocks: lifecycle hooks (`EventCallback` at 5 lifecycle points), structured logging (`StructuredLogger`), durable step records with timing data, and a visualization module (ASCII, HTML, graph/timeline). The gap is bridging these into industry-standard observability formats.

### Reasoning
If every run is an OpenTelemetry trace and every step is a span:
- **CI/CD integration:** Run agents in GitHub Actions, GitLab CI, or Jenkins with traces exported to Jaeger, Datadog, or Grafana Tempo. Debugging a failed agent run uses the same workflow as debugging a failed deployment.
- **Prometheus metrics:** Step duration histograms, failure rates by step type, LLM token usage counters, retry attempt distributions — all exportable via standard `/metrics` endpoints.
- **Alerting:** Set alerts on agent execution patterns (e.g., "notify if step X takes >5s or fails >3 times in an hour").
- **Correlation:** Link agent runs to the systems they interact with. If an agent calls an API, the trace ID propagates, connecting the agent's execution to the downstream service's traces.

The `EventCallback` mechanism already fires at the right lifecycle points. An OpenTelemetry callback implementation would translate events into spans without changing the core runtime.

### Implications
- `opentelemetry-api` and `opentelemetry-sdk` become optional dependencies (not required for local-only use).
- A built-in `OTelEventCallback` implementation translates lifecycle events into spans.
- Run metadata (`run_id`, `workflow_id`, `workflow_version`) maps to trace attributes.
- Step records map to child spans with `step_id`, `step_type`, `status`, `duration_ms`.
- LLM-specific span attributes: model name, token count, estimated cost.
- The visualization module can read from OTel-exported data, not just local storage — enabling remote run inspection.
