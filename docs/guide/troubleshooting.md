**Troubleshooting**

This guide covers common errors, their causes, and how to fix them.

---

**Common Errors**

- Unknown function: confirm the module and function name in `functions/`. Use `module.function_name` format.
- Unknown agent: confirm the agent id matches a YAML file in `agents/`. Check `agent.id` in the YAML.
- Unknown tool: confirm the tool class has a `name` attribute and is in `tools/`.
- Missing inputs: add `-i key=value` or set defaults in the workflow.
- YAML errors: fix indentation/syntax and run `ai run <workflow_ref>`; the runtime surfaces YAML parse and validation errors.
- Workflow hash mismatch on resume: the workflow YAML changed since the original run. Resume requires the same workflow definition.
- `BranchResolutionError`: no `when` condition matched and no `default` rule was provided.
- `WorkflowValidationError`: step references a future step's output, duplicate output keys across steps, or invalid retry config.
- `ReplayMismatchError`: reconstructed state diverges from recorded state during `--verify-state` replay.
- `safe_eval` rejection: branch condition uses disallowed syntax (imports, dunder access, lambdas, comprehensions).

**Cannot replay RUNNING run**

- A run must be in a terminal state (`COMPLETED`, `FAILED`, or `COMPLETED_WITH_ERRORS`) before it can be replayed.
- If a run is stuck in `RUNNING`, it may have been interrupted. Check the SQLite database directly or re-run the workflow.

**Workflow hash mismatch; cannot resume (`WorkflowIntegrityError`)**

- The workflow YAML changed since the original run.
- Resume requires the exact same workflow definition that produced the original run.
- Fix: revert your workflow changes, resume the run, then make your edits afterward. Or start a new run with the updated workflow.

**Replay data missing (`ReplayDataMissingError`)**

- Step or state persistence is incomplete for that run.
- This can happen if the runtime was killed mid-execution before persisting.
- Fix: re-run the workflow with the current runtime version.

**Replay state mismatch (`ReplayMismatchError`)**

- Reconstructed state diverges from the recorded `state_before` at a step.
- This indicates a data integrity issue or a runtime bug.
- Use `ai inspect <run_id> --state-history` to identify the divergence point.

**ModuleNotFoundError: yaml**

Install dependencies in the active environment:

```bash
pip install -r requirements.txt
```

**ToolNotFoundError: tool 'tools.xxx' not found**

- Confirm the tool class exists in the `tools/` directory.
- Confirm the class has a `name` attribute matching what the workflow references.
- Tool discovery skips classes whose names start with `_` and base classes imported from other modules.
- Built-in tools (`tools.echo`, `tools.http`, `tools.file`, `tools.shell`) are always available.

**Unknown function**

- Confirm the function exists in `functions/` and uses the correct qualified name format: `module.function_name`.
- Example: `stubs.generate_summary` resolves to `functions/stubs.py` → `generate_summary()`.
- Function resolution happens at workflow parse time — errors appear immediately, not during execution.
- If two modules define functions with the same name, use the qualified form to disambiguate.

**Agent not found**

- Confirm the agent YAML file exists in `agents/` and that `agent.id` in the file matches what the workflow references.
- Run `ai list` to see discovered agents.
- Version pinning: `agent: reviewer@v2` requires `agent.version: v2` in the YAML.

**BranchResolutionError**

- A step's `next:` rules were evaluated and no `when` condition matched, and no `default` was provided.
- Fix: add a `default:` fallback rule to your branching step.
- Branch conditions use `safe_eval()` — only `state` and `len()` are available. Check your expression syntax.

**WorkflowValidationError**

Common causes:
- A step reads output from a step that comes later in the workflow (forward reference).
- Two steps declare the same output key (output collision).
- `retry.attempts` is set to 0 (must be >= 1).
- A `goto` target references a step id that doesn't exist.
- Step ids are not unique.

**LLM API key errors**

- Keys are resolved from environment variables at call time.
- Ensure your `.env` file has the correct variable (e.g., `GEMINI_API_KEY=...`).
- Run `ai config --check` to verify which provider keys are available.
- The key env var name is configured in `runtime.yaml` under `llm.providers.<name>.api_key_env`.

**Step output contract violation**

- The step's runtime output keys don't match the declared `outputs` contract.
- Missing keys or undeclared extra keys will cause the step to fail.
- Fix: update either the `outputs` list in the workflow or the function/tool return value.

**safe_eval rejection**

Branch conditions are evaluated in a sandboxed environment. Rejected patterns include:
- `import` statements
- Dunder attributes (`__class__`, `__bases__`, etc.)
- Function calls other than `len()`
- Lambda expressions, list comprehensions, walrus operators
- Multiline expressions or expressions with semicolons

Valid examples: `state.inputs.issue == "bug"`, `len(state.steps.classify.tags) > 0`, `state.steps.classify.severity != "low"`

**Circular branch detected**

- A workflow's branch rules create a cycle (step A → step B → step A).
- The runtime detects this at execution time and raises an error.
- Fix: restructure your branch rules to avoid cycles.

**KeyError: 'Path not found: steps.\<step\>.\<key\>'**

- A downstream step references a key that the producing step doesn't output.
- For **agent steps**, the output key is controlled by `output_key` in the agent YAML (default: `text`). If the workflow reads `steps.summarize.summary`, the agent must set `output_key: summary`.
- For **function steps**, check that the function's return dict includes the expected key.
- For **tool steps**, check that `ToolResult.output` includes the expected key.
- Tip: run `ai inspect <run_id> --steps` to see actual step outputs.

**Empty or null step output**

- If a function returns `None` instead of a dict, or an agent returns an empty response, the step will fail.
- Functions must always return a dictionary.
- Agent pipeline issues may produce empty results — check the LLM provider response.

**Database locked / SQLite errors**

- The runtime uses WAL mode and thread-safe locking, but concurrent processes writing to the same `runtime.db` may conflict.
- Fix: use separate `--db-path` values for concurrent runs, or ensure only one process writes at a time.
