<!--
File: docs/guide/execution-walkthrough.md
Purpose: Step-by-step execution narrative for run, resume, replay, and visualization flows.
Description: Shows runtime bootstrapping, state transitions, persistence checkpoints, and debug loops.
Dependencies: CLI and runtime internals under src/agent_runtime.
Inputs/Outputs: Input for developer learning; output is operational mental model.
Side Effects: None.
-->

# Execution Walkthrough

This walkthrough is a textbook-style trace of what happens at runtime for a typical workflow run, then failure/resume, then replay.

Primary command used:

```bash
ai run workflows/example.yaml -i issue="Login API fails for invalid token"
ai run example_workflow -i issue="Login API fails for invalid token"
ai run summarizer -i text="Login API fails for invalid token"
```

## 1. Runtime bootstrapping

1. CLI parses arguments (`workflow_ref`, `db-path`, `-i` key=value inputs).
2. Runtime config is loaded from `runtime.yaml` (or defaults).
3. LLM registry is built from the `llm:` config block.
4. Tool registry is created: built-in tools (`echo`, `http`, `file`, `shell`) + auto-discovered tools from `tools/`.
5. Agent registry is built by scanning `agents/` for YAML definitions.
6. Memory manager is initialized with all four tiers (working, episodic, semantic, procedural).
7. Workflow is resolved by file path, `workflow_id`, `workflow_id@version`, or agent id — then validated.

Validation includes:
- Step ids unique
- Step type correctness (`agent`, `function`, `tool`)
- Branching rule structure and `goto` targets exist
- Retry policy values valid
- Step contract checks (future-read and output-collision prevention)
- Function resolution at parse time (fail fast)

## 2. Run creation

Executor creates a run record:
- `status = PENDING`
- `workflow_id` and `workflow_version` captured
- `workflow_hash` and `input_hash` captured
- Initial structured state:

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

Before step execution begins, the runtime calls `MemoryManager.hydrate_state(state)`, which reads from all four memory tiers (working, episodic, semantic, procedural) and enriches the initial state under `runtime.memory.<tier>`.

## 3. Step 1 execution — agent step (`summarize`)

Step definition:
- type: `agent`
- agent: `summarizer`
- inputs mapping: `issue: inputs.issue`

Detailed flow:
1. Runtime captures `state_before` snapshot.
2. Step input is materialized from state path mapping (`inputs.issue` → actual value).
3. Agent is resolved from the `AgentRegistry` by id.
4. `AgentExecutor` runs the agent's pipeline using its strategy (`single` or `react`).
5. The LLM client routes the call to the configured provider adapter (e.g., Gemini).
6. Agent returns an `AgentResult` with outputs, trace, and token usage.
7. Runtime writes output to `steps.summarize` namespace:

```json
{"summary": "The login API fails when an invalid token is provided."}
```

8. If `outputs` contract is declared, runtime validates output keys against the contract.
9. Runtime captures `state_after` snapshot.
10. Agent trace (iterations, tool calls, LLM responses) is stored in `StepExecution.agent_trace`.
11. Persists `StepExecution` record with timing (`duration_ms`) and increments state version.

## 4. Step 2 execution — tool step (`echo_summary`)

Step definition:
- type: `tool`
- tool: `tools.echo`
- inputs mapping: `message: steps.summarize.summary`

Detailed flow:
1. Runtime captures `state_before`.
2. Tool input is resolved from state paths.
3. Tool input is validated against `input_schema`.
4. Tool receives `RuntimeContext` (`run_id`, `step_id`, state, logger).
5. Runtime emits lifecycle events (`STEP_START`).
6. Tool's `execute()` method is called (with optional timeout via `asyncio.wait_for`).
7. Runtime emits `STEP_COMPLETE` event (with `tool_duration_ms`).
8. Tool output is written to `steps.echo_summary`.
9. Runtime captures `state_after` and persists step/state records atomically in a SQLite transaction.

## 5. Run completion

After the final step:
- `status → COMPLETED` (or `COMPLETED_WITH_ERRORS` in continue mode)
- `MemoryManager.persist_state(state)` writes final state to all memory tiers
- `RUN_COMPLETE` lifecycle event emitted with `total_duration_ms`
- Terminal timestamps persisted
- Run state frozen from runtime perspective

## 6. What inspect shows

Summary view:

```bash
ai inspect <run_id>
```

Shows:
- Run metadata (status, workflow id/version, timestamps)
- Ordered step statuses with durations
- Latest state snapshot

Step-centric view:

```bash
ai inspect <run_id> --steps
```

Shows per step:
- Status and attempt count
- Input and output
- Error / last_error (if any)
- Duration and timing

State timeline view:

```bash
ai inspect <run_id> --state-history
```

Shows:
- Initial state
- Per-step diffs (`+` added, `-` removed, `~` changed)
- Output and state-after snapshots

## 7. Failure and resume walkthrough

Trigger a failing workflow:

```bash
ai run workflows/samples/04_fail_and_resume.yaml -i issue="Login API fails"
```

Expected behavior:
- Earlier steps are `COMPLETED`
- Failing step is `FAILED`
- Run is `FAILED`

Resume:

```bash
ai resume <run_id>
```

Resume flow:
1. Validate run is resumable (`FAILED` only — rejects `COMPLETED` and `RUNNING`).
2. Validate workflow hash — raises `WorkflowIntegrityError` if the workflow changed since the original run.
3. Determine resume step from step history (retry the failed step, or resolve next from last completed).
4. Load latest state snapshot.
5. Continue execution from resume step with normal retry/branch logic.

## 8. Replay walkthrough (deterministic simulation)

Replay command:

```bash
ai replay <run_id>
```

Replay flow:
1. Load run record.
2. Load ordered step history.
3. Load initial state.
4. Iterate steps in recorded order.
5. Inject recorded transitions (`state_before` → `state_after`).
6. Print agent traces if present.

Important:
- Replay does **not** call agents, functions, or tools
- Replay does **not** mutate persisted run data
- Replay reconstructs state purely from stored snapshots

Verification mode:

```bash
ai replay <run_id> --verify-state
```

This checks reconstructed state matches recorded `state_before` at each step, raising `ReplayMismatchError` on divergence.

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
- `started_at`, `finished_at`, `duration_ms`
- `agent_trace` (for agent steps — includes LLM interactions and tool calls)

This is the foundation for deterministic debugging and reproducibility.

## 10. Practical debugging playbook

1. Run workflow.
2. Inspect with `--steps` to identify failing step and attempt pattern.
3. Inspect with `--state-history` to verify exact mutation point.
4. Use `ai state-diff <run_id>` for deep key-path state changes.
5. Resume if failure is recoverable.
6. Replay with `--verify-state` for deterministic postmortem.

This cycle is the intended developer loop of the runtime.

## 11. Visualization walkthrough

Generate a graph/timeline report for the same run:

```bash
ai visualize <run_id>
```

This creates:
- `.runs/<run_id>/visualization.html` (auto-opens in browser)

And includes:
- Execution graph (nodes, statuses, durations, attempts)
- Branch rule evaluations and selected path
- Step timeline with timing/error details
- Tool call table (arguments/results/latency)
- State timeline with `+`, `-`, `~` key-path diffs

For terminal-only debugging:

```bash
ai visualize <run_id> --ascii
ai visualize <run_id> --timeline
```
