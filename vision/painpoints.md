# Developer Pain Points Building AI Agents — and How ForrestRun Changes Them

**Audience:** Anyone evaluating ForrestRun, or considering building production AI workflows.

---

## 1. "It worked on my machine" — No Reproducibility

**Today:** You demo an agent to your team. It works. You run it again — different output, different routing, different failures. LLMs are non-deterministic. There is no way to reproduce a specific run to debug it, audit it, or prove it did what you think it did.

**With ForrestRun:** Every run is persisted with full state snapshots at every step. `ai replay <run_id>` re-executes from stored state with zero LLM calls and produces the exact same output. A run is a reproducible artifact, not a prayer.

---

## 2. The "printf Debugging" Trap — No Structured Observability

**Today:** An agent misbehaves. You sprinkle `print()` statements in your chain, re-run, and scroll through terminal output hoping to spot the issue. There's no structured way to see what each step received, what it produced, and how state evolved.

**With ForrestRun:** `ai inspect <run_id> --steps` shows input/output/state for every step. `ai state-diff <run_id>` shows exactly which keys changed between steps. `ai visualize <run_id> --html` renders an interactive timeline. Debugging is forensic, not archaeological.

---

## 3. The "Start From Scratch" Tax — No Resume

**Today:** A 7-step pipeline fails on step 5 because of a transient API error. You fix the issue and re-run the entire pipeline. Steps 1–4 burn tokens, time, and external API calls again — for nothing.

**With ForrestRun:** `ai resume <run_id>` picks up exactly where it failed. Steps 1–4 are skipped (their outputs are already persisted). You pay only for the work that still needs to happen.

---

## 4. Spaghetti State — No Ownership Model

**Today:** State is a mutable dict passed between steps. Step 3 overwrites a key that step 2 set. Step 5 reads a key that doesn't exist yet because step 4 was skipped. Nobody owns anything. Debugging state corruption means reading every line of every handler.

**With ForrestRun:** State is namespaced: `inputs.*`, `steps.<step_id>.*`, `runtime.*`. Each step writes to its own namespace. The `RuntimeState` manager enforces this. Cross-step collisions are structurally impossible.

---

## 5. The Invoice Surprise — No Cost Visibility

**Today:** You ship an agent pipeline. It runs 200 times a day. The LLM bill arrives: $4,000. Which step is burning tokens? Which agent is doing 15 ReAct iterations when 3 would suffice? You have no idea.

**With ForrestRun:** Token usage is persisted per step in SQLite. `ai inspect` surfaces token counts and cost. `--max-llm-tokens`, `--max-llm-cost-usd`, and `--max-llm-requests` let you set hard guardrails before a run even starts. The surprise never happens.

---

## 6. The Glue Code Explosion — Writing Infrastructure Instead of Logic

**Today:** Your "agent" is 300 lines of Python: 40 lines of actual logic, 260 lines of glue — parsing LLM output, routing to the next step, retrying on failure, serializing state, logging, handling timeouts. Every new agent starts with copy-pasting this scaffolding.

**With ForrestRun:** The runtime *is* the glue. You declare steps in YAML, point them at agents/functions/tools, and the runtime handles execution, retry, persistence, branching, and observability. Your code is the 40 lines of logic. Nothing else.

---

## 7. The "Works Once, Breaks Forever" Problem — No Regression Safety Net

**Today:** Your agent works. You ship it. Three weeks later, the LLM provider updates the model. Your agent silently starts producing worse output. You don't notice until a user complains. There's no way to compare "what it used to produce" with "what it produces now."

**With ForrestRun:** `ai replay <run_id> --verify-state` replays a historical run and compares the output state against what was originally produced. If the outputs diverge, you know immediately. Replay is your regression test for LLM behavior.

---

## 8. The Invisible Failure — No Output Contracts

**Today:** You ask the LLM to return JSON with `severity` and `summary` keys. It returns a markdown blob. Your downstream step crashes or, worse, silently consumes garbage and propagates it. There's no schema enforcement between steps.

**With ForrestRun:** Steps declare `output_contract` with required keys. The runtime validates outputs after every step. If the LLM hallucinates the structure, the step fails explicitly with a clear error — not silently downstream.

---

## 9. The "Can't Hand It Off" Problem — Workflows Buried in Code

**Today:** Your agent pipeline lives in `run_pipeline.py` — 500 lines of imperative Python. A new team member joins. They need to understand the control flow, the ordering, the branching logic, the retry behavior, all encoded in Python. Onboarding takes a week.

**With ForrestRun:** The workflow is a YAML file. A new developer reads it top-to-bottom and understands: these are the steps, this is the order, this is the branching condition, this is the retry policy. The execution contract is *declarative and readable*.

---

## 10. Provider Lock-in — Rewriting Agents When You Switch Models

**Today:** You built your pipeline on OpenAI. You want to try Anthropic. Your prompt parsing, tool-call format, response handling — all different. You rewrite half the agent. Switching LLMs is a multi-day migration.

**With ForrestRun:** Agent definitions are provider-agnostic. The adapter layer (OpenAI, Anthropic, Gemini) handles native function calling, message format, and response parsing. Change `default_model` in `runtime.yaml` and your agents run on the new provider with zero code changes.

---

## 11. The "No Undo" Problem — Side Effects Without Safety

**Today:** Your agent calls an external API (sends a Slack message, creates a Jira ticket). The next step fails. On retry, the message is sent *again*. There's no idempotency tracking, no way to know which external actions already happened.

**With ForrestRun:** Step execution records track exactly which steps completed and which failed. Resume skips completed steps, including those with side effects. The runtime gives you the data to build idempotent tool wrappers rather than silently re-executing everything.

---

## 12. Branching is Just If-Else — No Declarative Routing

**Today:** You need to route an agent pipeline based on LLM output: if severity is critical, escalate; if low, log and close. You write Python if-else chains. The routing logic is tangled with execution logic. Adding a new branch means editing code.

**With ForrestRun:** Branching is declarative in YAML: `when: state.steps.classify.severity == "critical"`. The runtime evaluates branch conditions in a sandboxed expression language. Adding a new routing path means adding a YAML block, not touching Python.

---

## 13. Memory Amnesia — Every Run Starts from Zero

**Today:** Your support triage agent processes 100 tickets a week. It learns nothing. Each ticket is classified from scratch. Patterns that a human would recognize ("this customer always reports the same issue") are invisible to the agent.

**With ForrestRun:** Multi-tier memory — working, episodic, semantic, and procedural — gives agents context across runs. Episodic memory records what happened. Semantic memory stores retrievable knowledge. Procedural memory will mine episode history for reusable patterns.

---

## 14. Testing is Impossible — You Can't Assert on a Vibes Machine

**Today:** How do you test an agent? You can't mock the LLM consistently. You can't snapshot intermediate state. You can't replay a specific run. So you write no tests, or you write flaky integration tests that break every time the model changes.

**With ForrestRun:** Replay *is* the test. Capture a known-good run, replay it, verify state matches. The mock LLM fallback lets you write fast deterministic tests without API calls. Step-level state snapshots let you assert on any intermediate value.

---

## 15. Config Drift Between Environments

**Today:** Dev uses `gpt-4o` with temperature 0.7. Staging uses `gpt-3.5-turbo` with temperature 0. Production uses a fine-tuned model. The three environments produce wildly different behavior. Nobody knows which config is canonical. A model swap in prod requires a code deploy.

**With ForrestRun:** `runtime.yaml` is the single source of truth. Model, temperature, retry policy, and timeout are all declared in one file, version-controlled alongside the workflow. Config is infrastructure-as-code, not tribal knowledge.

---

## 16. Rate Limiting Across Concurrent Runs

**Today:** You run 10 agents in parallel. They all hit the same LLM provider. Rate limits kick in. Half the runs fail. You add retry logic with jitter. Then you add a semaphore. Then you add a token bucket. Congratulations, you've written a rate limiter instead of solving your actual problem.

**With ForrestRun:** The LLM client layer is the single choke point for all API calls (roadmap: built-in rate-limit-aware scheduling). Centralized control means you can enforce concurrency limits in one place rather than in every agent.

---

## 17. No Graceful Degradation

**Today:** A step fails and the entire pipeline aborts. There's no way to say "if this step fails, use a fallback value and keep going" or "skip this optional enrichment and proceed with what we have."

**With ForrestRun:** `on_error` policies per step (roadmap: `fallback` and `skip` modes) let you declare degradation behavior in YAML. The runtime handles it. Your pipeline doesn't shatter on the first transient error.

---

## 18. No Fan-Out / Fan-In

**Today:** You need to run the same step on 50 items — classify 50 tickets, summarize 50 documents. You write a `for` loop. It runs sequentially. You rewrite it with `asyncio.gather()`. Now you need to collect results, handle partial failures, and merge state. That's another 100 lines of glue.

**With ForrestRun:** Fan-out/fan-in is a roadmap primitive. Declare a step that maps over a list, the runtime parallelizes execution and merges results back into state. Partial failures are tracked per item, not per pipeline.

---

## 19. Heartbeats for Long-Running Workflows

**Today:** A ReAct agent enters a 10-iteration loop. It takes 4 minutes. The caller has no idea if it's still working, stuck, or dead. There's no liveness signal. The only options are "wait and hope" or "kill it and start over."

**With ForrestRun:** Step-level `duration_ms` tracking is already persisted. Heartbeat emission (roadmap) will provide liveness signals for long-running steps, enabling callers to distinguish "still thinking" from "stuck."

---

## 20. Secrets Leak into Traces

**Today:** You pass an API key as an input. It gets logged. It appears in the trace. It's stored in the SQLite database. Anyone with access to the run history can see it. You discover this in a security audit three months later.

**With ForrestRun:** Trace redaction (roadmap) will automatically scrub sensitive values from persisted state and CLI output. Secret patterns are configurable. Observability doesn't mean exposure.

---

## The Shift

| Without ForrestRun | With ForrestRun |
|---|---|
| Agents are fragile scripts | Agents are durable workflows |
| Debugging is guesswork | Debugging is forensic inspection |
| Failure means start over | Failure means resume from checkpoint |
| State is a shared mutable mess | State is namespaced and auditable |
| LLM costs are invisible | Costs are tracked per step with hard limits |
| Switching providers = rewrite | Switching providers = one config change |
| Testing = "run it and see" | Testing = deterministic replay + assertions |
| Onboarding = "read the code" | Onboarding = "read the YAML" |
| Every run starts from zero | Agents learn across runs via multi-tier memory |
| Config is tribal knowledge | Config is version-controlled YAML |

---

## Core Thesis

AI workflows deserve the same execution guarantees that we've built for every other kind of production software — persistence, reproducibility, observability, and crash recovery. ForrestRun is the runtime that provides them.
