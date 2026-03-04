# agentic-runtime

Minimal, local-first workflow runtime for agentic systems.

**Environment**
- Conda env name: `agent_runtime`

**Install**
```bash
pip install -r requirements.txt
```

**Initialize a project**
```bash
PYTHONPATH=src ./ai init
```

**Run the example workflow**
```bash
PYTHONPATH=src ./ai run workflows/example.yaml
```

**Run with a custom issue**
```bash
PYTHONPATH=src ./ai run workflows/example.yaml --issue "Login API fails for invalid token"
```

**Run tests**
```bash
PYTHONPATH=src pytest -q
```

**Docs**
- `/Users/yashagrawal/Documents/agentic-runtime/docs/USAGE.md`
- `/Users/yashagrawal/Documents/agentic-runtime/docs/ARCHITECTURE.md`
