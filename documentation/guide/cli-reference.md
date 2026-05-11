# CLI Reference

This document provides a comprehensive reference for all `ai` command-line interface commands and options.

## Global Options

These options can be applied to any command that supports them (notably `run`, `resume`, and `metrics`).

| Flag | Description |
|---|---|
| `--db-path <path>` | Override the default SQLite database path (default: `runtime.db`). |

---

## 1. Project Initialization

Setup command map:

| Command | What it does |
|---|---|
| `ai init` | Base scaffold only (folders + `.env` + `runtime.db` + `runtime.yaml`) |
| `ai config` | Configure provider/model/key settings |
| `ai quickstart` | `init` + `config` + first run |
| `ai onboard` / `ai start` | Interactive guided setup wizard |
| `ai` (no args) | Opens home screen with setup/run/inspect/visualize actions |

### `ai init`
Initialize a new, empty workflow project.

- **`--path <path>`**: Target directory (default: `.`).

Creates these folders:
- `agents/`
- `functions/`
- `tools/`
- `workflows/`

Creates these files:
- `.env`
- `runtime.db`
- `runtime.yaml`

`ai init` intentionally does not create starter files inside those folders.

### `ai quickstart`
The "Golden Path": initialize, configure, and run a starter workflow in one go.

- **`--path <path>`**: Project root.
- **`--sample <name>`**: Starter workflow to run. Options: `starter` (default), `branching`, `research`, `pipeline`.

### `ai onboard`
Guided setup wizard for a new or existing project.

- **`--path <path>`**: Project root.

Alias: `ai start`

---

## 2. Configuration

### `ai config`
Configure LLM providers, API keys, and model settings.

- **`--path <path>`**: Project root containing `runtime.yaml` (default: `.`).
- **`--provider <name>`**: Choose from `openai`, `anthropic`, `gemini`.
- **`--api-key-env <name>`**: Environment variable name for the API key (e.g., `OPENAI_API_KEY`).
- **`--api-key <value>`**: Directly provide the API key value (written to `.env`).
- **`--model <id>`**: Default model ID for this provider.
- **`--base-url <url>`**: Base URL for local/proxy providers.
- **`--temperature <float>`**: Model temperature.
- **`--max-tokens <int>`**: Model max tokens.
- **`--no-dotenv`**: Do not write API key values into `.env`.
- **`--no-default`**: Do not update default provider/model fields.
- **`--check`**: Validate current credentials and provider availability.

Common setup recipes:

```bash
# New project, explicit setup flow
ai init
ai config
ai config --check

# Fastest first run
ai quickstart

# Deterministic no-key first run
ai quickstart --sample branching

# Guided wizard
ai onboard
# or
ai start
```

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

### `ai test`
Run project-authored tests across workflows, agents, functions, and tools.

- **`scope`**: One of `all` (default), `workflows`, `agents`, `functions`, `tools`.
- **`targets`**: Optional target filters (e.g. specific workflow or agent names).
- **`--path <path>`**: Project root containing the testable directories (default: `.`).
- **`--pytest-args ...`**: Extra arguments forwarded to `pytest`.

### `ai export`
Export a portable project bundle that can run on another install of this runtime.

- **`--path <path>`**: Project root (default: `.`).
- **`-o, --output <path>`**: Output archive path (default: `<project>.agentic-export.tar.gz`).
- **`--no-tools`**: Exclude the `tools/` directory from the bundle.

The export includes `runtime.yaml`, `workflows/`, `agents/`, `functions/`, and `prompts/` (if present). `.env` is intentionally excluded.

### `ai import`
Import a portable bundle into a project directory and optionally run a workflow.

- **`bundle`**: Path to the `.tar.gz` export bundle.
- **`--path <path>`**: Target directory to extract into (default: `.`).
- **`--run <workflow>`**: Workflow path to run after import (relative to target dir).

Example:
```bash
ai import ./my-project.agentic-export.tar.gz --path ./my-project --run workflows/example.yaml
```

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
