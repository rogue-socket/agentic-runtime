# Project TODOs

This document summarizes all inline TODOs found in the codebase, categorized for planning.

## Completed
  - **Phase 2: Native Function Calling** - LLM adapters for OpenAI/Anthropic/Gemini and ReAct strategy fully support native tool calls.
  - **Token Usage Persistence** - Usage captured in executor, persisted in SQLite, and surfaced in CLI.
  - **Step-Level Timeouts** - `timeout_ms` supported in workflow YAML and enforced by executor.
  - **Quickstart Fallback** - `ai quickstart` supports `mock` LLM fallback when API keys are missing.


## Roadmap
  - `agent_runtime/logging.py:41`: TODO(roadmap): Add OpenTelemetry trace/span export so runtime events
  - `agent_runtime/logging.py:44`: TODO(roadmap): Add optional webhook/callback event sink so external
  - `agent_runtime/logging.py:46`: TODO(roadmap): Emit Prometheus-compatible metrics (run count, step
  - `agent_runtime/core.py:860`: TODO(roadmap): Multi-agent composition: allow a step to invoke
  - `agent_runtime/llm/adapters.py:247`: TODO(roadmap): Support streaming (stream=True) for token-level feedback.
  - `agent_runtime/llm/adapters.py:351`: TODO(roadmap): Add streaming support for token-level feedback.
  - `agent_runtime/llm/adapters.py:462`: TODO(roadmap): Support streaming for token-level feedback.
  - `agent_runtime/memory/procedural.py:107`: TODO(roadmap): Consider LLM-assisted rule extraction from episode narratives
  - `agent_runtime/memory/semantic.py:366`: TODO(roadmap): Vector-similarity retrieval for semantic memory.
  - `agent_runtime/agent/definition.py:51`: TODO(roadmap): Consider adding "agent" pipeline step type for nested agent calls
  - `agent_runtime/storage/base.py:24`: TODO(roadmap): Implement a PostgreSQL backend for team/production deployments.
  - `agent_runtime/storage/base.py:27`: TODO(roadmap): Consider a remote-capable storage adapter (e.g., S3 + DynamoDB)
  - `agent_runtime/storage/base.py:29`: TODO(roadmap): Storage is currently single-user — one SQLite file

## Pain-point
  - `agent_runtime/config.py:60`: TODO(pain-point): Config Drift Between Environments - Dev uses
  - `agent_runtime/core.py` (run API semantics): TODO(pain-point): Workflow `inputs.*.default` values are not auto-applied when calling `Executor.run` directly. Consider applying declared defaults in core execution path (or expose a helper) so SDK behavior matches CLI ergonomics.
  - `agent_runtime/resume.py:86`: TODO(pain-point): Selective Step Re-Execution - Resume works for
  - `agent_runtime/__init__.py:79`: TODO(pain-point): Export/Wire-Into-Product -
  - `agent_runtime/core.py:169`: TODO(pain-point): Latency Budgets - duration_ms tracks how long
  - `agent_runtime/core.py:284`: TODO(pain-point): Heartbeats for Long-Running Workflows - A react
  - `agent_runtime/core.py:571`: TODO(pain-point): Secrets in Agent Traces -
  - `agent_runtime/core.py:578`: TODO(pain-point): Hallucination Guardrails -
  - `agent_runtime/core.py:624`: TODO(pain-point): Retry-Aware Observability - Emit a
  - `agent_runtime/core.py:639`: TODO(pain-point): Structured Output Parsing - Output
  - `agent_runtime/core.py:662`: TODO(pain-point): No Graceful Degradation - on_error is
  - `agent_runtime/core.py:848`: TODO(pain-point): Fan-Out/Fan-In - Steps currently execute sequentially.
  - `agent_runtime/replay.py:38`: TODO(pain-point): Cold-Path Amnesia - Add branch-coverage tracking across
  - `agent_runtime/replay.py:41`: TODO(pain-point): Snapshot Testing for LLM Outputs - Replay works for
  - `agent_runtime/utils.py:132`: TODO(pain-point): Template Injection - User-supplied state values are
  - `agent_runtime/visualization/ascii_renderer.py:19`: TODO(pain-point): Aggregate Observability - Visualization renders a
  - `agent_runtime/llm/client.py:16`: TODO(pain-point): Rate Limiting Across Concurrent Runs - One
  - `agent_runtime/llm/client.py:22`: TODO(pain-point): Model Regression Detection - When you swap
  - `agent_runtime/agent/strategies.py:180`: TODO(pain-point): Cost Accounting - Persist aggregated token usage on each

## Ux
  - `agent_runtime/cli.py:27`: TODO(ux): ICP is solo dev / small team building an agent. The CLI
  - `agent_runtime/cli.py:2189`: TODO(ux): Improve diff granularity beyond top-level keys.
  - `agent_runtime/cli.py:2190`: TODO(ux): Add CLI graph visualization for branching workflows.
  - `agent_runtime/cli.py:2197`: TODO(ux): Handle large state output safely (pagination or truncation).
  - `agent_runtime/visualization/html_renderer.py:125`: TODO(ux): Replace text edge list with interactive graph rendering (e.g., Mermaid) without external network dependencies.

## Security
  - `agent_runtime/core.py:658`: TODO(security): Enforce immutability rules:
  - `agent_runtime/utils.py:261`: TODO(security): P2 — Without this check, expressions like

## Engineering
  - `agent_runtime/resume.py:84`: TODO(eng): Support step-level idempotency verification before resuming side-effecting steps.
  - `agent_runtime/resume.py:85`: TODO(eng): Support retry conditions (e.g., retry only on specific error types).
  - `agent_runtime/function_resolver.py:107`: TODO(eng): module-caching - Modules are cached in sys.modules under
  - `agent_runtime/core.py:837`: TODO(eng): Provide an opt-in helper to run sync APIs in async contexts by
  - `agent_runtime/cli.py:2196`: TODO(eng): Support snapshot compression for large states.
  - `agent_runtime/utils.py:293`: TODO(eng): expression-language - Expand the expression language for
  - `agent_runtime/visualization/html_renderer.py:34`: TODO(eng): html-template - This renderer builds the entire HTML page
  - `agent_runtime/tools/discovery.py:99`: TODO(eng): module-caching - Same sys.modules caching concern as
  - `agent_runtime/memory/working.py:84`: TODO(eng): dict-order - Relies on dict insertion order (Python 3.7+)
  - `agent_runtime/agent/strategies.py:10`: TODO(eng): make accumulation configurable (option: clean slate per iteration)
  - `agent_runtime/agent/strategies.py:535`: TODO(eng): make accumulation configurable (option: clean slate per iteration)
  - `agent_runtime/agent/strategies.py:547`: TODO(eng): make referencing configurable (options: named ids, positional prev.*, accumulator)
  - `agent_runtime/storage/sqlite.py:118`: TODO(eng): Use SAVEPOINT for nested transactions if callers
  - `workflows/example.yaml`, `agent-one/workflows/example.yaml`, `test-agent/workflows/example.yaml`: TODO(eng): Deduplicate quickstart example workflow definitions or generate them from one source to avoid behavior drift.
  - `workflows/branching_triage.yaml`, `agent-one/workflows/branching_triage.yaml`, `test-agent/workflows/branching_triage.yaml`: TODO(eng): Consolidate duplicated deterministic quickstart workflows into a shared template/build step.
  - `workflows/data_pipeline.yaml`, `agent-one/workflows/data_pipeline.yaml`, `test-agent/workflows/data_pipeline.yaml`: TODO(eng): Consolidate duplicated data pipeline workflow copies and enforce sync via CI drift check.
  - `tests/test_workflow_file_coverage.py`: TODO(eng): Add a CI guard that fails when a new workflow file is added without execution/parse coverage.

## Uncategorized
  - `agent_runtime/memory/semantic.py:19`: implemented.  See the TODO at the bottom of this file for the

## Audit Findings (2026-03-28)
  - `workflows/samples/07_agent_and_function.yaml:4`: TODO(ux): Keep sample header comments aligned with actual step agent ids; add doc lint if possible.
  - `test-agent/workflows/shopping.yaml:14`: TODO(ux): Keep embedded run instructions scoped to the containing project folder to avoid copy-paste confusion.

