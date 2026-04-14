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

## Step 2: Pick Your Setup Command

Use this quick chooser:

- `ai quickstart`: Best default. Creates/initializes the project, walks provider config, and runs a first workflow
- `ai init`: Creates only the base project skeleton (no starter files inside folders)
- `ai config`: Configures provider/model/key settings for an existing project
- `ai onboard` (or `ai start`): Interactive setup wizard

If you want the fastest path to first success, use `ai quickstart`.

## Step 3: Golden Path (Recommended)
Create a new directory for your agent and run quickstart.

```bash
mkdir my-first-agent
cd my-first-agent

# Initialize + configure + run first workflow
ai quickstart
```

`ai quickstart` prompts for provider configuration when needed.

1. **Select Provider**: Choose `openai`, `anthropic`, or `gemini`.
2. **Set API Key**: Enter your key when prompted. The runtime will offer to save it to a `.env` file (which is gitignored).
3. **Set Default Model**: Choose a model (e.g., `gpt-4o`, `claude-3-opus`).

If you don't have an API key yet, you can still see a successful run using a deterministic sample:
```bash
ai quickstart --sample branching
```

## Step 4: Manual Setup Path (Optional)
If you prefer explicit, step-by-step setup:

```bash
mkdir my-first-agent
cd my-first-agent

# Base scaffold only: folders + .env + runtime.db + runtime.yaml
ai init

# Configure provider/model/key
ai config

# Optional readiness check
ai config --check
```

## Step 5: Your First Run
If you used the default `ai quickstart`, it already ran a sample workflow for you. To run it again with different input:

```bash
ai run workflows/example.yaml -i issue="The login page is returning 401 errors"
```

## Step 6: Observe and Debug
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

## Step 7: Make it Yours
1. **Define a new Agent**: Add a YAML file to `agents/`.
2. **Add a Python function**: Add a script to `functions/`.
3. **Update the Workflow**: Edit `workflows/example.yaml` to use your new components.
4. **Refresh Docs**: Rebuild the doc index if you add new documentation files.
   ```bash
   ai docs
   ```

Next, read the [CLI Reference](cli-reference.md) for a full list of commands or the [Usage Guide](usage.md) for common scenarios.
