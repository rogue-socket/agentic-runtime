**Getting Started**

Welcome! This guide is intentionally beginner-friendly. It will get you from zero to a successful run, then show the smallest possible change you can make to feel real progress.

**Install**

::::tabs
:::tab Conda (recommended)
```bash
conda activate agentic-runtime
pip install -r requirements.txt
pip install -e .
```
:::tab venv
```bash
python -m venv .venv

# macOS/Linux:
source .venv/bin/activate

# Windows:
.venv\Scripts\activate

pip install -r requirements.txt
pip install -e .
```
::::

**Quickstart (0 → 1)**

```bash
mkdir my-agent
cd my-agent
ai quickstart
```

`ai quickstart` does three things:
1. Initializes a project scaffold (`workflows/`, `agents/`, `functions/`, `tools/`, `runtime.yaml`).
2. Writes example files: a workflow definition (`workflows/example.yaml`), agent definitions (`agents/summarizer.yaml`, `agents/fixer.yaml`), example functions (`functions/`), and example tools (`tools/example_tool.py`).
3. Runs the setup flow to configure an LLM provider and optional API key, then executes the workflow so you see a successful run immediately.

**Run Again With Different Input**

```bash
ai run workflows/example.yaml -i issue="Login API fails for invalid token"
```

What is `issue`? It is the workflow input named `issue`. In `workflows/example.yaml`, the workflow declares an input called `issue`, and `-i issue="..."` supplies its value at run time. You can replace the text with any problem description you want the workflow to process.

To see full structured logs (LLM calls, token usage), add `-v`:

```bash
ai run workflows/example.yaml -v -i issue="Login API fails for invalid token"
```

**Inspect And Visualize**

```bash
ai inspect <run_id> --steps
ai visualize <run_id> --html
```

**Make Your First Change (1 → 2)**

```bash
cp workflows/example.yaml workflows/my_workflow.yaml
```

Edit `workflows/my_workflow.yaml` to add a new step or swap an agent reference, then run it:

```bash
ai run workflows/my_workflow.yaml
```

The three step types you can use in workflows:
- `type: agent` — calls an LLM agent defined in `agents/`. The agent's `output_key` field controls the key name in the output dict (e.g., `output_key: summary` means downstream steps read `steps.<step_id>.summary`).
- `type: function` — calls a Python function from `functions/`. The function's return dict keys become the output.
- `type: tool` — calls a tool class from `tools/`. The `ToolResult.output` dict keys become the output.

If you want the full walkthrough, read [`docs/guide/manual.md`](manual.md) next.

If you prefer a visual navigator, open [`docs/index.html`](../index.html) in a browser.
