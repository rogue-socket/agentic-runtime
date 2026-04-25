# Getting Started

Welcome! This guide gets you from zero to a running workflow with ForrestRun.

## Install

```bash
pip install forrestrun
```

For development (from source):
```bash
pip install -e ".[dev]"
```

## Option A: Python SDK (Recommended)

The fastest way to run a workflow programmatically:

```python
from agent_runtime import run_workflow

result = run_workflow(
    "workflows/example.yaml",
    inputs={"issue": "The login page is returning 401 errors"},
)

print(result.status)       # "COMPLETED"
print(result.final_state)  # full state tree with every step's output
```

In async contexts (FastAPI, Jupyter, etc.):

```python
from agent_runtime import run_workflow_async

result = await run_workflow_async(
    "workflows/research.yaml",
    inputs={"topic": "AI agents"},
)
```

## Option B: CLI

ForrestRun also ships a CLI for interactive development and debugging.

### Scaffold a New Project

```bash
mkdir my-agent && cd my-agent
ai quickstart
```

`ai quickstart` creates the project structure, configures your LLM provider, and runs the starter workflow.

1. **Select Provider**: Choose `openai`, `anthropic`, or `gemini`.
2. **Set API Key**: Enter your key when prompted. The runtime saves it to `.env` (gitignored).
3. **Set Default Model**: Choose a model (e.g., `gpt-4o`, `claude-sonnet-4-20250514`).

No API key yet? Run a deterministic sample without one:
```bash
ai quickstart --sample branching
```

### Manual Setup (Optional)

If you prefer explicit, step-by-step setup:

```bash
mkdir my-agent && cd my-agent
ai init          # scaffold directories + config files
ai config        # configure provider/model/key
ai config --check  # verify key availability
```

### Run a Workflow

```bash
ai run workflows/example.yaml -i issue="The login page is returning 401 errors"
```

### Observe and Debug

```bash
ai runs                        # list recent runs
ai inspect latest --steps      # step-by-step breakdown
ai visualize latest            # HTML timeline
ai resume <run_id>             # resume from failure point
ai replay <run_id> --verify-state  # deterministic replay
```

## Project Structure

Whether you use the SDK or CLI, a ForrestRun project looks like this:

```
my-agent/
  agents/          # LLM agent definitions (YAML)
  functions/       # deterministic Python functions
  tools/           # custom tool implementations
  workflows/       # workflow definitions (YAML)
  runtime.yaml     # config (provider, model, limits)
  .env             # API keys
```

## Next Steps

- [Writing Workflows](workflows.md) — define your pipeline in YAML
- [Writing Agents](writing-agents.md) — LLM-backed reasoning steps
- [Writing Functions](writing-functions.md) — deterministic Python logic
- [Writing Tools](writing-tools.md) — external action steps
- [CLI Reference](cli-reference.md) — full command listing
