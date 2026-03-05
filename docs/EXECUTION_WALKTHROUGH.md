# Execution Walkthrough

Command:
```bash
PYTHONPATH=src ./ai run workflows/example.yaml --issue "Login API fails for invalid token"
```

## Step-by-step Execution

1. **CLI parses arguments**
   - Loads the workflow path and the initial `issue` string.
   - Sets the SQLite DB path to `runtime.db` unless overridden.

2. **Handler registry setup**
   - Registers the built-in handler `generate_summary` in `StepHandlerRegistry`.

3. **Workflow YAML is loaded and validated**
   - `workflows/example.yaml` is parsed.
   - Workflow name is extracted.
   - Steps are validated and converted into `StepDefinition` objects.

4. **Runtime components are created**
   - `SQLiteStorage` initializes DB schema in `runtime.db`.
   - `MemoryManager` is constructed with four tiers (Working, Episodic, Semantic, Procedural).
   - `ToolRegistry` is created with a default `tools.echo` handler.
   - `Executor` is instantiated with steps + storage + memory + tools.

5. **Run is created**
   - A new `Run` record is created with status `PENDING`, then updated to `RUNNING`.
   - Initial state is set to:
     ```json
     {
       "inputs": { "issue": "Login API fails for invalid token" },
       "steps": {}
     }
     ```
   - State version `0` is persisted.

6. **Step 1 executes: `generate_summary` (model)**
   - Executor snapshots state and hydrates memory into it.
   - Step input is built from `inputs.issue`.
   - Handler runs with step input and returns:
     - `{ "summary": "Issue related to login API failing when token is invalid." }`
   - State is merged into `steps.generate_summary`.
   - Memory tiers persist the updated state.
   - StepExecution is saved with status `COMPLETED`.
   - State version `1` is persisted.

7. **Step 2 executes: `tools.echo` (tool)**
   - Executor snapshots state and hydrates memory.
   - Tool input is resolved from `steps.generate_summary.summary`:
     - `{ "message": "Issue related to login API failing when token is invalid." }`
   - Tool returns:
     - `{ "tool_output": {"message": "Issue related to login API failing when token is invalid."} }`
   - State is merged into `steps.echo_tool`.
   - Memory tiers persist the updated state.
   - StepExecution is saved with status `COMPLETED`.
   - State version `2` is persisted.

8. **Run completes**
   - Run status set to `COMPLETED`.
   - Completed timestamp recorded in SQLite.

## Final State (Example)
```json
{
  "inputs": {
    "issue": "Login API fails for invalid token"
  },
  "steps": {
    "generate_summary": {
      "summary": "Issue related to login API failing when token is invalid."
    },
    "echo_tool": {
      "tool_output": {
        "message": "Issue related to login API failing when token is invalid."
      }
    }
  }
}
```

## Persistence Side Effects
- `runs` table: one row for the run.
- `steps` table: two rows (generate_summary, echo_tool).
- `state_versions` table: three rows (initial, after step 1, after step 2).
