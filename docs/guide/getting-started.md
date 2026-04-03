# Getting Started
Welcome! This guide is the "golden path" to your first successful run with Agentic Runtime.

## Step 1: Prepare Environment
We recommend using Conda to manage your Python environment.

```bash
# Create or activate the environment
conda activate agent_runtime

# Install dependencies and the CLI in editable mode
pip install -r requirements.txt
pip install -e .
```

## Step 2: Initialize Your Project
Create a new directory for your agent and initialize the structure.

```bash
mkdir my-first-agent
cd my-first-agent

# Scaffold the project (workflows, agents, functions, tools)
ai quickstart
```

## Step 3: Configure LLM Keys
The `ai quickstart` command (or `ai setup`) will prompt you to configure your provider.

1. **Select Provider**: Choose `openai`, `anthropic`, or `gemini`.
2. **Set API Key**: Enter your key when prompted. The runtime will offer to save it to a `.env` file (which is gitignored).
3. **Set Default Model**: Choose a model (e.g., `gpt-4o`, `claude-3-opus`).

If you don't have an API key yet, you can still see a successful run using a deterministic sample:
```bash
ai quickstart --sample branching
```

## Step 4: Your First Run
If you used the default `ai quickstart`, it already ran a sample workflow for you. To run it again with different input:

```bash
ai run workflows/example.yaml -i issue="The login page is returning 401 errors"
```

## Step 5: Observe and Debug
The runtime records every detail of the execution.

- **Check Results**: View the summary of recent runs.
  ```bash
  ai runs
  ```
- **Inspect Step Details**: See exactly what happened at each step.
  ```bash
  ai inspect latest --steps
  ```
- **Visualize the Flow**: Open a beautiful HTML dashboard of the run.
  ```bash
  ai visualize latest --html
  ```

## Step 6: Make it Yours
1. **Define a new Agent**: Add a YAML file to `agents/`.
2. **Add a Python function**: Add a script to `functions/`.
3. **Update the Workflow**: Edit `workflows/example.yaml` to use your new components.
4. **Refresh Docs**: Rebuild the doc index if you add new documentation files.
   ```bash
   ai docs
   ```

Next, read the [Manual](manual.md) for a deep dive into schemas and advanced features.
