# ForrestRun Examples

These examples demonstrate ForrestRun's capabilities for building AI agent workflows.

## Minimal Example

**File**: `minimal/run.py`

The simplest ForrestRun workflow — a 10-line inline YAML pipeline with no external dependencies or API keys.

```bash
cd minimal
python run.py
```

**What it shows**:
- `RuntimeBuilder` fluent configuration
- Inline YAML workflow definition
- In-memory SQLite database (`:memory:`)
- `tools.echo` for deterministic output
- Run accessor methods (`run.step_names`, `run.get_output()`)

## Shopping Agent Example

**Directory**: `shopping_agent/`

An autonomous agent that browses a mock shop, evaluates products, creates a cart, and checks out. Demonstrates ReAct multi-turn reasoning with tool use.

```bash
cd shopping_agent
python run.py
# or with a custom shopping list:
python run.py --shopping-list "Buy a laptop under 1500 dollars"
```

**What it shows**:
- Custom tool registration with `RuntimeBuilder.with_tool()`
- ReAct agent strategy with multi-turn tool use
- Agent system prompts and pipeline definitions
- Structured workflow with agent → tool steps
- Configuration via `runtime.yaml`
- In-memory mock shop (no external services required)

**Files**:
- `run.py` — entry point with RuntimeBuilder setup
- `runtime.yaml` — config (model, provider, paths)
- `workflow.yaml` — 2-step workflow (agent.shopper → tool.echo)
- `agents/shopper.yaml` — ReAct agent definition with tool access
- `tools/shop.py` — mock shop backend (products, carts, orders)
- `tools/shop_tools.py` — ForrestRun tool wrappers

---

## Next Steps

After running these examples:

1. **Modify the minimal example**: Change the inline YAML workflow to add a second step.
2. **Extend the shopping agent**: Add a `payer` agent step to simulate payment processing.
3. **Build your own**: Use `RuntimeBuilder` in your FastAPI app, Jupyter notebook, or Lambda function.

See the [documentation](../documentation/) for detailed guides on workflows, agents, and tools.
