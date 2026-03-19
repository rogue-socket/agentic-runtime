**Troubleshooting**

This guide covers common errors and how to fix them quickly.

**Cannot replay RUNNING run**

- Wait for the run to complete or fail, then replay.

**Workflow hash mismatch; cannot resume**

- The workflow changed since the original run.
- Resume requires a compatible workflow definition.

**Replay data missing**

- Step/state persistence is incomplete for that run.
- Re-run the workflow with the current runtime version.

**ModuleNotFoundError: yaml**

Install dependencies in the active environment:

```bash
pip install -r requirements.txt
```
