# AI Testing Framework Design

Date: 2026-04-11
Status: Draft for implementation planning

## Why this exists

The runtime now supports CLI test scaffolding and scoped execution commands.
The next step is defining a first-class test framework for AI workflows, agents, tools, and functions.
This document captures the proposed architecture, principles, and phased rollout.

## Product Goal

Move from basic test execution to an AI-native evaluation framework that supports:

1. deterministic correctness
2. quality and semantic scoring
3. robustness and stability checks

## North Star

Build a Spec + Eval framework, not just a pytest wrapper.

Core model:

1. Developers declare behavior in structured test specs
2. Runtime executes scenarios and records rich traces
3. Assertions run through multiple oracles
4. Results are persisted as regression artifacts and can be replayed

## Inspiration Sources

1. pytest parametrization and fixtures for deterministic checks
2. contract testing for step interfaces and tool schemas
3. LLM evaluation patterns (rubric grading, dataset runs)
4. trace-first debugging architectures for workflow execution
5. property-based testing mindset for edge and adversarial exploration

## Proposed Test Case Model

Use one unified test schema across target types.
A field like target.kind drives the execution harness.

Common sections:

1. metadata: id, tags, priority, owner
2. target: kind + identifier
3. inputs: payload or matrix
4. assertions_hard: deterministic pass/fail checks
5. assertions_soft: score-based checks
6. stability: repeated runs + pass policy
7. budgets: latency/token/cost limits
8. snapshot: optional golden capture/compare policy

## Example Spec Shape

```yaml
id: refund_route_happy_path
target:
  kind: workflow
  id: payments_refund
inputs:
  issue: "User charged twice and asks for refund"
  country: "US"
assertions_hard:
  - path: steps.route.output.intent
    equals: refund
  - path: run.status
    equals: COMPLETED
  - path: trace.tool_calls
    contains: tools.report_builder
assertions_soft:
  - metric: rubric
    rubric: "Response is actionable, safe, and concise"
    min_score: 0.8
  - metric: semantic_similarity
    reference: "Provide refund steps and timeline"
    min_score: 0.75
stability:
  runs: 3
  pass_if: "2_of_3"
budgets:
  max_latency_ms: 5000
  max_tokens: 12000
  max_cost_usd: 0.35
```

## Three Oracle Engine

1. Contract Oracle
- exact values
- schemas
- required tool calls
- branch decisions
- state-path assertions

2. Quality Oracle
- rubric grading
- semantic similarity
- threshold-based acceptance

3. Metamorphic Oracle
- controlled input transformations
- invariance checks
- sensitivity checks

Why this matters:
Golden snapshots alone catch drift but miss deeper brittleness.
Metamorphic checks catch hidden fragility early.

## CLI Experience Vision

Examples:

1. ai test all
2. ai test workflows
3. ai test workflows checkout
4. ai test agents advisor
5. ai test tools --update-golden
6. ai test workflows --flaky-policy rerun-2

Desired behavior:

1. predictable discovery by scope
2. targeted execution with filters
3. rich failure bundles for debugging
4. machine-readable outputs for CI

## Reporting Artifacts

Each test run should produce:

1. human summary table
2. machine report (JSON + JUnit)
3. per-failure trace bundle with:
- input payload
- step outputs and diffs
- tool calls
- token/cost/latency
- failing assertions and reasons

## Novel Layer: Confidence Budgets

In addition to pass/fail, each suite enforces:

1. deterministic pass rate threshold
2. semantic quality floor
3. variability ceiling across repeated runs

Example release gate:

- deterministic checks pass 100%
- semantic score >= 0.78
- variance <= 0.12

This gives AI-native release confidence, not just binary correctness.

## Phased Delivery Plan

Phase A (foundation)

1. spec parser
2. deterministic assertions
3. scoped runners
4. JSON report output

Phase B (quality)

1. rubric scoring
2. semantic similarity checks
3. threshold policy enforcement

Phase C (robustness)

1. metamorphic test support
2. confidence budget computation
3. flaky analytics and retry policy hooks

Phase D (closed loop)

1. auto case generation from production failures
2. replay-to-test conversion workflows
3. trend dashboards over quality and stability

## Open Design Questions

1. How opinionated should v1 schema be vs plugin-driven assertion modules?
2. Should soft assertions run by default, or behind flags for cost control?
3. How should budgets be enforced in local runs vs CI contexts?
4. Should golden updates require explicit approval metadata?

## Next Concrete Step

Define v1 schema and assertion vocabulary with strict validation rules, then implement Phase A end-to-end.
