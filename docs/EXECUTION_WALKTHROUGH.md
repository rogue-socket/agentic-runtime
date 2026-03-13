# Execution Walkthrough

This walkthrough is a textbook-style trace of what happens at runtime for a typical workflow run, then failure/resume, then replay.

Primary command used:

```bash
PYTHONPATH=src ./ai run workflows/example.yaml -i issue="Login API fails for invalid token"
PYTHONPATH=src ./ai run example_workflow -i issue="Login API fails for invalid token"
PYTHONPATH=src ./ai run code_review_agent@v2 -i issue="Login API fails for invalid token"
```

## 1. Runtime bootstrapping

1. CLI parses arguments (`workflow_ref`, `db-path`, `-i` key=value inputs).
2. Handler registry is created and model handlers are registered.
3. Tool registry is created and default tools (for example `tools.echo`) are registered.
4. Workflow is resolved either by file path, `workflow_id`, or `workflow_id@version`, then validated.

Validation includes:
- step ids unique
- step type correctness
- branching rule structure
- `goto` targets exist
- retry policy values valid
- step contract checks (future-read and output-collision prevention)

## 2. Run creation

Executor creates a run record:
- `status = PENDING`
- `workflow_id` and `workflow_version` captured
- `workflow_hash` and `input_hash` captured
- initial structured state:

```json
{
  "inputs": {
    "issue": "Login API fails for invalid token"
  },
  "steps": {},
  "runtime": {}
}
```

Then run transitions to `RUNNING` and initial state is persisted as `state_versions.version = 0`.

### Memory hydration

Before step execution begins, the runtime calls `MemoryManager.hydrate_state(state)`, which reads from all four memory tiers (working, episodic, semantic, procedural) and enriches the initial state.

## 3. Step 1 execution (`generate_summary`)

Step definition:
- type: `model`
- inputs mapping: `issue: inputs.issue`

Detailed flow:
1. Runtime captures `state_before` snapshot.
2. Step input is materialized from state path mapping.
3. Handler receives a `RuntimeState` wrapper of step input.
4. Handler returns structured output, for example:

```json
{"summary": "Issue related to login api failing when invalid token."}
```

5. Runtime writes output to `steps.generate_summary` namespace.
6. If `outputs` contract is declared, runtime validates output keys against the contract.
7. Runtime captures `state_after` snapshot.
8. Persists `StepExecution` and increments state version.

## 4. Step 2 execution (`echo_tool`)

Step definition:
- type: `tool`
- inputs mapping: `message: steps.generate_summary.summary`

Detailed flow:
1. Runtime captures `state_before`.
2. Tool input is resolved from state paths.
3. Tool input is validated against tool schema.
4. Tool receives `RuntimeContext` (`run_id`, `step_id`, state, logger).
5. Runtime emits tool events (`TOOL_START`, `TOOL_SUCCESS` or `TOOL_ERROR`).
6. Tool output is written to `steps.echo_tool`.
7. Runtime captures `state_after` and persists step/state records.

## 5. Run completion

After final step:
- `status -> COMPLETED` (or `COMPLETED_WITH_ERRORS` in continue mode)
- `MemoryManager.persist_state(state)` writes final state to all memory tiers
- terminal timestamps persisted
- run state frozen from runtime perspective

## 6. What inspect shows

Summary view:

```bash
PYTHONPATH=src ./ai inspect <run_id>
```

Shows:
- run metadata
- ordered step statuses
- duration and attempt counts
- latest state

Step-centric view:

```bash
PYTHONPATH=src ./ai inspect <run_id> --steps
```

Shows per step:
- status
- attempts
- output
- error / last_error

State timeline view:

```bash
PYTHONPATH=src ./ai inspect <run_id> --state-history
```

Shows:
- initial state
- per-step diffs (`+`, `-`, `~`)
- output and state-after snapshots

## 7. Failure and resume walkthrough

Trigger a failing workflow:

```bash
PYTHONPATH=src ./ai run workflows/samples/04_fail_and_resume.yaml -i issue="Login API fails"
```

Expected behavior:
- earlier steps may be `COMPLETED`
- failing step is `FAILED`
- run is `FAILED`

Resume:

```bash
PYTHONPATH=src ./ai resume <run_id>
```

Resume flow:
1. Validate run is resumable.
2. Validate workflow hash.
3. Determine resume step from step history.
4. Load latest state snapshot.
5. Continue execution from resume step with normal retry/branch logic.

## 8. Replay walkthrough (deterministic simulation)

Replay command:

```bash
PYTHONPATH=src ./ai replay <run_id>
```

Replay flow:
1. Load run record.
2. Load ordered step history.
3. Load initial state.
4. Iterate steps in recorded order.
5. Inject recorded transitions (`state_before` -> `state_after`).

Important:
- replay does not call model handlers
- replay does not call tools
- replay does not mutate persisted run data

Verification mode:

```bash
PYTHONPATH=src ./ai replay <run_id> --verify-state
```

This checks reconstructed state matches recorded `state_before` at each step.

## 9. Data persisted per step (for debugging)

Each step execution persists:
- `execution_index`
- `status`
- `attempt_count`
- `input`
- `output`
- `error` and `last_error`
- `state_before`
- `state_after`
- timing (`started_at`, `finished_at`, `duration_ms`)

This is the foundation for deterministic debugging and reproducibility.

## 10. Practical debugging playbook

1. Run workflow.
2. Inspect with `--steps` to identify failing step and attempt pattern.
3. Inspect with `--state-history` to verify exact mutation point.
4. Resume if failure is recoverable.
5. Replay with `--verify-state` for deterministic postmortem.

This cycle is the intended developer loop of the runtime.

## 11. Visualization walkthrough

Generate a graph/timeline report for the same run:

```bash
PYTHONPATH=src ./ai visualize <run_id>
```

This creates:
- `.runs/<run_id>/visualization.html`

And includes:
- execution graph (nodes, statuses, durations, attempts)
- branch rule evaluations and selected path
- step timeline with timing/error details
- tool call table (arguments/results/latency)
- state timeline with `+`, `-`, `~` key-path diffs

For terminal-only debugging:

```bash
PYTHONPATH=src ./ai visualize <run_id> --ascii
PYTHONPATH=src ./ai visualize <run_id> --timeline
```
