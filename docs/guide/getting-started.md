**Getting Started**

Welcome! This guide is intentionally beginner-friendly. It will get you from zero to a successful run, then show the smallest possible change you can make to feel real progress.

**Install**

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

**Quickstart (0 → 1)**

```bash
mkdir my-agent
cd my-agent
ai quickstart
```

`ai quickstart` does three things:
1. Initializes a project scaffold (`workflows/`, `handlers/`, `tools/`, `agents/`, `runtime.yaml`).
2. Writes a workflow definition (`workflows/example.yaml`) and an agent definition (`agents/example_agent.yaml`) that points to it.
3. Runs the setup flow to configure an LLM provider and optional API key, then executes the workflow so you see a successful run immediately (this workflow uses the LLM handler, so it will call your configured provider).

If you want to run the agent definition instead of the workflow file, use:

```bash
ai run example_agent@v1
```

**Run Again With Different Input**

```bash
ai run workflows/example.yaml -i issue="Login API fails for invalid token"
```

What is `issue`? It is the workflow input named `issue`. In `workflows/example.yaml`, the workflow declares an input called `issue`, and `-i issue="..."` supplies its value at run time. You can replace the text with any problem description you want the workflow to process.

**Inspect And Visualize**

```bash
ai inspect <run_id> --steps
ai visualize <run_id> --html
```

**Make Your First Change (1 → 2)**

```bash
cp workflows/example.yaml workflows/my_workflow.yaml
```

Edit `workflows/my_workflow.yaml` to swap a step handler or add a new step, then run it:

```bash
ai run workflows/my_workflow.yaml
```

If you add a new handler, put it in `handlers/` and reference it by name in the workflow. The runtime auto-discovers handler functions and tool classes from those folders.

If you want the full walkthrough, read [`docs/guide/manual.md`](manual.md) next.

If you prefer a visual navigator, open [`docs/site/index.html`](../site/index.html) in a browser.
