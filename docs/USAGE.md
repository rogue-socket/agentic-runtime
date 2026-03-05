# Usage

## Run a workflow
```bash
PYTHONPATH=src ./ai run workflows/example.yaml
```

## Run with a custom issue
```bash
PYTHONPATH=src ./ai run workflows/example.yaml --issue "Login API fails for invalid token"
```

## Initialize a project
```bash
PYTHONPATH=src ./ai init
```

## Run tests
```bash
PYTHONPATH=src pytest -q
```

## Inspect a run
```bash
PYTHONPATH=src ./ai inspect <run_id>
```

## Inspect step details
```bash
PYTHONPATH=src ./ai inspect <run_id> --steps
```

## Inspect state history
```bash
PYTHONPATH=src ./ai inspect <run_id> --state-history
```

## Resume a failed run
```bash
PYTHONPATH=src ./ai resume <run_id>
```

## Replay a run
```bash
PYTHONPATH=src ./ai replay <run_id>
```

## Replay with verification or limits
```bash
PYTHONPATH=src ./ai replay <run_id> --verify-state
PYTHONPATH=src ./ai replay <run_id> --until summarize
PYTHONPATH=src ./ai replay <run_id> --step-by-step
```
