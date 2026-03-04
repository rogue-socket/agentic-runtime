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
