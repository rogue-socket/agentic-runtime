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

**Inspect a run**
```bash
PYTHONPATH=src ./ai inspect <run_id>
```

**Inspect step details**
```bash
PYTHONPATH=src ./ai inspect <run_id> --steps
```

**Inspect state history**
```bash
PYTHONPATH=src ./ai inspect <run_id> --state-history
```

**Resume a failed run**
```bash
PYTHONPATH=src ./ai resume <run_id>
```

**Replay a run (deterministic, read-only)**
```bash
PYTHONPATH=src ./ai replay <run_id>
```
Replay injects recorded step outputs and state snapshots; it does not call tools or models.

**State manager**
Runtime execution uses `RuntimeState` (not raw dict mutation) for controlled state access, step output namespacing, snapshots, and diff support.

**Docs**
- `/Users/yashagrawal/Documents/agentic-runtime/docs/USAGE.md`
- `/Users/yashagrawal/Documents/agentic-runtime/docs/ARCHITECTURE.md`
