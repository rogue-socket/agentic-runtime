# CLI Reference

This document provides a comprehensive reference for all `ai` command-line interface commands and options.

## Global Options

These options can be applied to any command that supports them (notably `run`, `resume`, and `metrics`).

| Flag | Description |
|---|---|
| `--db-path <path>` | Override the default SQLite database path (default: `runtime.db`). |

---

## 1. Project Initialization

### `ai init`
Initialize a new, empty workflow project.

- **`--path <path>`**: Target directory (default: `.`).

### `ai quickstart`
The "Golden Path": initialize, configure, and run a starter workflow in one go.

- **`--path <path>`**: Project root.
- **`--sample <name>`**: Starter workflow to run. Options: `starter` (default), `branching`, `research`, `pipeline`.

### `ai onboard`
Guided setup wizard for a new or existing project.

- **`--path <path>`**: Project root.

---

## 2. Configuration

### `ai setup`
Configure LLM providers, API keys, and model settings.

- **`--provider <name>`**: Choose from `openai`, `anthropic`, `gemini`, `local`.
- **`--api-key-env <name>`**: Environment variable name for the API key (e.g., `OPENAI_API_KEY`).
- **`--api-key <value>`**: Directly provide the API key value (written to `.env`).
- **`--model <id>`**: Default model ID for this provider.
- **`--temperature <float>`**: Model temperature.
- **`--max-tokens <int>`**: Model max tokens.
- **`--check`**: Validate current credentials and provider availability.

---

## 3. Execution

### `ai run`
Execute a workflow.

- **`<workflow>`**: **(Required)** Path to YAML file or `workflow_id[@version]`.
- **`-i, --input KEY=VALUE`**: Pass workflow inputs. Repeatable.
- **`-v, --verbose`**: Enable detailed JSON logging including LLM calls and tool usage.
- **`--debug`**: Launch the interactive debugger.
- **`--breakpoint <spec>`**: Set an initial breakpoint (e.g., `step:summarize`).

#### LLM Control Flags (Available on `run` and `resume`):
- **`--llm-rate-limit-rpm <int>`**: Global requests-per-minute cap.
- **`--max-llm-requests <int>`**: Hard cap on requests per run.
- **`--max-llm-tokens <int>`**: Hard cap on total tokens per run.
- **`--max-llm-cost-usd <float>`**: Hard cap on estimated cost.

---

## 4. Observability & Debugging

### `ai inspect`
View the detailed outcome of a specific run.

- **`<run_id>`**: **(Required)** The unique ID of the run.
- **`--steps`**: Show detailed output and errors for every step.
- **`--state-history`**: Show how state mutated after every step.
- **`--diff-limit <int>`**: Cap the number of state changes shown per step (default: 20).

### `ai state-diff`
Compare state changes across steps or for a specific step.

- **`<run_id>`**: **(Required)**
- **`--step <id>`**: Filter diff to a specific step.
- **`--full`**: Show the complete diff without truncation.

### `ai visualize` (alias: `viz`)
Visualize run execution as a graph or timeline.

- **`<run_id>`**: **(Required)**
- **`--html`**: (Default) Generate and open an interactive HTML visualization.
- **`--ascii`**: Render a tree-like graph in the terminal.
- **`--timeline`**: Show a text-based chronological event list.
- **`--no-open`**: Do not auto-open the HTML browser window.

---

## 5. Management

### `ai list`
List all discovered agent definitions in the project.

- **`--agents-dir <path>`**: Directory to scan (default: `agents/`).

### `ai runs`
List historical runs stored in the database.

- **`--limit <int>`**: Number of recent runs to show (default: 20).
- **`--html`**: Open a browsable dashboard of all runs.

### `ai metrics`
Show aggregate health, latency, and trend metrics.

- **`--window-days <int>`**: Calculation window for trends (default: 7).
- **`--latency-target-ms <int>`**: Target p95 latency for success scoring (default: 5000).
- **`--json`**: Output the full report as raw JSON.

### `ai docs`
Manage automated documentation.

- **`--path <path>`**: Project root.
- **`--no-workflow-reference`**: Skip generating the auto-reference doc.
- **`--no-site-index`**: Skip rebuilding the web UI search index.

---

## 6. Failure Recovery

### `ai resume`
Continue a failed run from the last successful checkpoint.

- **`<run_id>`**: **(Required)**
- **`--workflow <path>`**: Optionally provide the YAML to validate against the original.

### `ai replay`
Deterministically re-execute a run (stores nothing, invokes no tools).

- **`<run_id>`**: **(Required)**
- **`--step-by-step`**: Pause and wait for user input between steps.
- **`--verify-state`**: Verify that re-execution produces the same state as the record.
