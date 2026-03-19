# Runtime Positioning Notes — 2026-03-17

## Goal

Position `agentic-runtime` as the execution runtime for agents, not just a history system. The runtime should feel like an active control plane that runs, governs, and observes agent workloads.

## Why It Currently Reads As “Git For Agents”

1. The public narrative highlights replay, resume, and inspection more than live execution.
2. The CLI surface is strong on forensics (`inspect`, `replay`, `visualize`) and light on operational control (`serve`, `schedule`, `cancel`, `monitor`).
3. Quickstart and samples still lead with stub handlers, which hides real execution and makes the system feel like a recorder, not a runner.

## What A Runtime Must Feel Like

1. Always-on execution with a worker or server mode.
2. Operational control primitives: cancel, pause, retry, prioritize.
3. Resource governance: timeouts, rate limits, concurrency limits.
4. Observability: live events, streaming output, and metrics.
5. Safety and isolation: tool sandboxing, secrets, input policy checks.
6. Programmatic embed: a first-class SDK API, not just a CLI.

## Product Shifts To Align With “Runtime”

1. Add `ai serve` or `ai worker` to accept runs over HTTP or a local queue.
2. Add cancellation and scheduling primitives to the CLI and SDK.
3. Add streaming and real-time execution events.
4. Make the default scaffold run a real LLM step with a single command.
5. Introduce an SDK wrapper for run, resume, replay, and events.

## Messaging Update

Positioning statement draft:

“`agentic-runtime` is the execution runtime for AI agents. It runs workflows deterministically, enforces state contracts, and provides operational control and observability so agent systems can be debugged, resumed, and trusted in production.”

## Near-Term Deliverables

1. Update `ai init` to scaffold a real LLM workflow.
2. Add a `ai quickstart` command that runs and visualizes an LLM step.
3. Add an event hook or streaming channel for step and LLM progress.
4. Document the runtime control plane: run, cancel, resume, replay, inspect.

