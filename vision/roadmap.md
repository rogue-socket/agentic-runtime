# ForrestRun — Product Roadmap

**Owner:** ForrestRun core team  
**Horizon:** ~6 months  
**North Star:** Become the default execution substrate for AI agent workflows for indie developers and small teams, with a path to enterprise adoption.

---

## Target user

**Today:** Indie developers and small teams building internal AI pipelines — support triage, code review, data extraction, research agents.

**Horizon:** Platform/infra teams at mid-size and large orgs who need deterministic, auditable, production-ready agent execution — with auth, multi-tenancy, and observability.

The early-adopter persona is a developer who has already built something fragile with LangChain or raw API calls and wants reliability and debuggability. They will tolerate a learning curve for YAML if it buys them crash recovery, replay, and observability out of the box.

---

## What we are

We are a **deterministic execution substrate for AI agent workflows** — not a framework, not a UI, not an agent marketplace.

We are the thing that makes agents run reliably in production:
- You define what to do (YAML workflows, agent definitions, functions, tools).
- We guarantee how it runs (atomic persistence, resume, replay, branching, observability).

---

## 0.2.0 — "Production reliable"

**Theme:** The runtime should be trustworthy in the hands of a developer who is building something real.

**Release criteria: all of the following must ship.**

### Must have

| Feature | Why | Files |
|---|---|---|
| **Native function calling (all 3 adapters)** | Text parsing is the #1 production breakage point. ReAct agents silently drop tool calls when the LLM deviates from the markdown format. | `llm/types.py`, `llm/adapters.py`, `llm/client.py`, `agent/strategies.py` |
| **`ai quickstart` works without pre-config** | First experience must produce an output, not a stack trace. Needs stub/mock fallback when no API key is set. | `cli.py`, `workflows/`, `agents/` |
| **Token usage persisted to SQLite + shown in `ai inspect`** | Developers must be able to see which step is burning tokens before the invoice arrives. | `agent/strategies.py`, `core.py`, `storage/sqlite.py`, `cli.py` |
| **Step-level `timeout` in workflow YAML** | A ReAct agent with 10 iterations and a slow model can block for minutes with no signal. `timeout_ms` on `StepDefinition`. | `core.py`, `workflow.py` |
| **Async-safe sync wrappers** | `asyncio.run()` fails in FastAPI, Jupyter, any running event loop. Blocks all SDK adoption. | `core.py` |

### Should have

| Feature | Why | Files |
|---|---|---|
| **Agent version pinning in workflow YAML** | `agent: code_reviewer@v1` already parses and resolves correctly. Needs documentation, tests, and CLI display. | `workflow.py` (done), `docs/` |
| **Trace redaction** | Raw expanded prompts containing PII are stored in SQLite and surfaced via `ai inspect`. | `core.py` |

### Won't have (next release)

- DAG / parallel step execution
- PostgreSQL storage backend
- LLM streaming
- Multi-agent / sub-workflow composition
- Auth / multi-tenancy

---

## 0.3.0 — "Composable"

**Theme:** Workflows can compose multiple agents and sub-workflows naturally.

| Feature | Notes |
|---|---|
| **Multi-agent composition** | A workflow step can invoke a sub-workflow. Enables orchestrator patterns. |
| **Per-step `optional: true`** | A failing enrichment step falls back to a declared default and continues. |
| **Richer branch expression language** | `in`, `.startswith()`, arithmetic, `.lower()` in `when` conditions. |
| **Output contract value validation** | Enum, type, regex validation on contract keys — not just key presence. |
| **LLM streaming** | Token-level events via `EventCallback` for long-running model steps. |
| **Procedural memory** | Implement the documented stub: mine episodic history for patterns. |

---

## 1.0.0 — "Enterprise ready"

**Theme:** Safe to run inside a real organization with multiple teams and shared infrastructure.

| Feature | Notes |
|---|---|
| **Auth / access control** | Who can run which workflows, read which runs, resume which failures. |
| **Multi-tenancy** | Namespace isolation for projects/teams sharing one runtime instance. |
| **PostgreSQL storage backend** | For horizontal scale and shared-state deployments. |
| **Audit log** | Immutable record of who ran what, when, with what inputs. |
| **OpenTelemetry / Prometheus** | Wire `EventCallback` to OTel spans and Prometheus counters. |
| **Remote storage** | S3 + DynamoDB for run state (for serverless/distributed execution). |
| **Tool permissions + sandboxing** | Declare which tools each agent is allowed to call in which contexts. |

---

## Ongoing (any release)

| Area | Work |
|---|---|
| **Zero-dep commitment** | Maintain `urllib`-only HTTP. No new runtime dependencies without explicit sign-off. |
| **Test coverage** | Every new feature ships with tests. The 448-test baseline is a floor, not a target. |
| **Documentation accuracy** | Docs are updated in the same PR as code changes. No doc drift. |
| **CLI DX** | Every new CLI command gets help text, example output, and an error message that tells you how to fix the problem. |

---

## Not on the roadmap (by design)

- **An agent marketplace / hub** — we are infrastructure, not a directory.
- **A UI / dashboard** — HTML visualization exists; a hosted dashboard is a different product.
- **Managed cloud offering** — the runtime is local-first by design.
- **LangChain / CrewAI compatibility shims** — we are a clean alternative, not a wrapper.

---

*Last updated: 2026-03-24*
