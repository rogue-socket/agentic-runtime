# Usage

This guide is command-first and scenario-oriented.

## 1. Prerequisites

- Use conda env: `agent_runtime`
- Install dependencies:

```bash
pip install -r requirements.txt
```

## 2. Initialize project scaffold

```bash
PYTHONPATH=src ./ai init
```

Creates baseline workflow scaffold under `workflows/`.

## 3. Run workflows

Workflow files should declare:

```yaml
workflow:
  id: my_workflow
  version: v1
```

## Run default example

```bash
PYTHONPATH=src ./ai run workflows/example.yaml
```

## Run latest workflow version by id

```bash
PYTHONPATH=src ./ai run example_workflow
```

Resolution rule:
- runtime scans `./workflows/**/*.yaml` and `./workflows/**/*.yml`
- selects highest numeric `vN` for matching `workflow.id`

## Run a specific workflow version

```bash
PYTHONPATH=src ./ai run code_review_agent@v2
```

## Run with custom issue input

```bash
PYTHONPATH=src ./ai run workflows/example.yaml --issue "Login API fails for invalid token"
PYTHONPATH=src ./ai run code_review_agent@v1 --issue "Login API fails for invalid token"
```

## Use a custom SQLite path

```bash
PYTHONPATH=src ./ai run workflows/example.yaml --db-path runtime.db
```

## 4. Inspect runs

## Summary mode

```bash
PYTHONPATH=src ./ai inspect <run_id>
```

Use when you want:
- run status
- ordered step outcome
- latest state snapshot

## Step-centric mode

```bash
PYTHONPATH=src ./ai inspect <run_id> --steps
```

Use when you want:
- per-step output
- attempt counts
- exact error details

## State evolution mode

```bash
PYTHONPATH=src ./ai inspect <run_id> --state-history
```

Use when you want:
- initial state
- per-step mutation history
- state diffs and post-step snapshots

## 5. Resume failed runs

```bash
PYTHONPATH=src ./ai resume <run_id>
```

Use when:
- a run failed mid-flow
- completed steps should not re-run

Behavior:
- validates run status and workflow compatibility
- restores latest state
- continues from resume step

## 6. Deterministic replay

## Replay full run

```bash
PYTHONPATH=src ./ai replay <run_id>
```

## Replay with consistency verification

```bash
PYTHONPATH=src ./ai replay <run_id> --verify-state
```

## Replay until a specific step

```bash
PYTHONPATH=src ./ai replay <run_id> --until summarize
```

## Replay interactively (step-by-step)

```bash
PYTHONPATH=src ./ai replay <run_id> --step-by-step
```

Replay guarantees:
- no tool invocation
- no model invocation
- no persisted data mutation

## 7. Sample workflows

Run all curated samples:

```bash
PYTHONPATH=src ./ai run workflows/samples/01_linear_issue_summary.yaml --issue "Login API fails for invalid token"
PYTHONPATH=src ./ai run workflows/samples/02_retry_and_backoff.yaml --issue "Login API fails for invalid token"
PYTHONPATH=src ./ai run workflows/samples/03_branching_triage.yaml --issue "bug"
PYTHONPATH=src ./ai run workflows/samples/04_fail_and_resume.yaml --issue "Login API fails"
PYTHONPATH=src ./ai run workflows/samples/versioning/code_review_agent_v1.yaml --issue "Login API fails"
PYTHONPATH=src ./ai run workflows/samples/versioning/code_review_agent_v2.yaml --issue "Login API fails"
```

What each sample demonstrates:
- `01_linear_issue_summary.yaml`: baseline linear execution
- `02_retry_and_backoff.yaml`: retry semantics and attempt visibility
- `03_branching_triage.yaml`: deterministic conditional branching
- `04_fail_and_resume.yaml`: failure path and resume flow
- `versioning/code_review_agent_v1.yaml` + `versioning/code_review_agent_v2.yaml`: workflow version evolution

## 7.1 Step contracts workflow pattern

Use contract mode when you want explicit read/write boundaries between steps.

```yaml
workflow:
  id: contracts_demo
  version: v1
inputs_contract: [issue]
steps:
  - id: generate_summary
    type: model
    handler: generate_summary
    inputs: [issue]
    outputs: [summary]
```

Behavior:
- Contract input keys are validated against available state symbols.
- Contract output keys are checked for collisions across steps.
- Runtime enforces that step output keys match declared `outputs`.

## 8. Common workflows for developers

## A) Debug a failure

1. Run workflow.
2. Inspect step details.
3. Inspect state history.

```bash
PYTHONPATH=src ./ai run workflows/samples/04_fail_and_resume.yaml --issue "Login API fails"
PYTHONPATH=src ./ai inspect <run_id> --steps
PYTHONPATH=src ./ai inspect <run_id> --state-history
```

## B) Recover after fixing an adapter/config

```bash
PYTHONPATH=src ./ai resume <run_id>
```

## C) Reproduce exactly for postmortem

```bash
PYTHONPATH=src ./ai replay <run_id> --verify-state --step-by-step
```

## 9. Test suite

```bash
PYTHONPATH=src pytest -q
```

For targeted checks:

```bash
PYTHONPATH=src pytest -q tests/test_replay.py
PYTHONPATH=src pytest -q tests/test_state_manager.py
```

## 10. Troubleshooting

## `Cannot replay RUNNING run`
- Wait for run completion/failure, then replay.

## `Workflow hash mismatch; cannot resume`
- Workflow changed since original run.
- Resume requires compatible workflow definition.

## `Replay data missing`
- Step/state persistence is incomplete for that run.
- Re-run workflow with current runtime version.

## `ModuleNotFoundError: yaml`
- Install dependencies in the active environment:

```bash
pip install -r requirements.txt
```

## 11. State diff debugging

Show state changes across all recorded steps:

```bash
PYTHONPATH=src ./ai state-diff <run_id>
```

Show state changes for one step id:

```bash
PYTHONPATH=src ./ai state-diff <run_id> --step plan
```

Output markers:
- `+` added key path
- `-` removed key path
- `~` modified key path

## 12. Run visualization

ASCII graph + timeline:

```bash
PYTHONPATH=src ./ai visualize <run_id> --ascii
```

Timeline-focused text:

```bash
PYTHONPATH=src ./ai visualize <run_id> --timeline
```

HTML visualization (default mode):

```bash
PYTHONPATH=src ./ai visualize <run_id>
```

Output:
- file path `.runs/<run_id>/visualization.html`
- runtime attempts to open the file in the default browser

HTML includes:
- execution graph view
- branch decision table
- step timeline with attempts/duration
- tool call table (args/result/latency)
- state timeline with per-step diffs
