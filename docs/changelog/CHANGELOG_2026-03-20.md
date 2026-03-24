# Changelog — 2026-03-20

## Bug fixes (P0)

- **EpisodicMemory connection leak**:
  Switched from per-call `sqlite3.connect()` to persistent `self._conn` with an
  explicit `close()` method.  Fixes `PermissionError` on Windows temp cleanup.

- **SemanticMemory connection leak**:
  Same persistent-connection fix applied to `SemanticMemory`.  Additionally fixed
  an FTS5 query bug (`WHERE fts MATCH ?` used a table alias — SQLite requires
  the full table name in MATCH clauses).

- **File handle leak in FileTool**:
  `open().read()` replaced with `with open() as f:` in `tools/file.py`.

- **Dead code in ToolDiscovery**:
  Removed orphaned `discover()` function sitting outside the class body in
  `tools/discovery.py`.

## Dead code removal (P1)

- **Deleted `handler_discovery.py`**:
  Module had zero imports anywhere in the codebase.

- **Deleted `handlers/` directories**:
  Root `handlers/` and `agent-one/handlers/` removed — all handler logic lives
  in `steps.py` and `llm/handler.py`.

- **Pruned unused step handlers**:
  Removed `classify_severity`, `diagnose_issue`, `propose_fix`, and
  `review_code` from `steps.py`.  Only `generate_summary` and the registry
  remain.

## Deprecations (P1)

- **Workflow `type: model` removed**:
  Current workflow validation accepts only `agent`, `function`, and `tool`.
  `model` remains valid only inside agent pipelines (`agents/*.yaml`).

## Safety (P1)

- **Circular branch detection**:
  `Executor.__execute_steps_loop` tracks visited step IDs and raises
  `BranchResolutionError` on revisit, preventing infinite loops.

## New tests

- `test_safe_eval.py` — 30 tests: valid expressions, adversarial/injection inputs, edge cases.
- `test_executor_e2e.py` — 18 tests: function steps, agent steps, circular branch detection.
- `test_working_memory.py` — scratch store, sliding window, active task, MemoryTier protocol.
- `test_semantic_memory.py` — stub mode, SQLite CRUD, FTS5 search, tags, metadata, MemoryTier protocol.
- `test_config.py` — defaults, YAML loading, config blocks, LLM wiring, CLI overrides.
- `test_tool_discovery.py` — valid/multiple tools, invalid modules, empty dirs, registry integration.
- `test_openai_adapter.py` — 10 tests: success, system prompt, params, custom URL, error cases, client routing.
- `test_llm_handler.py` — 15 tests: prompt/response, templates, system prompt, response_key, metadata, params, validation errors.
- `test_cli.py` — 36 tests: _coerce_value, _parse_env_line, _redact, _build_input_state, _init_project, run_cli dispatch (init, list, validate).

## Documentation

- **Status doc updated**:
  Added Phase 2 agent modules (`definition.py`, `executor.py`, `prompts.py`,
  `registry.py`, `strategies.py`) to module inventory.  Removed deleted
  `handler_discovery.py`.  Updated test coverage table (15 → 29 files).
  Added sample workflows 05–07 to samples table.

## Housekeeping

- **Duplicate YAML key**:
  Removed duplicate `summary` key in `workflows/samples/05_llm_call.yaml`.

## Backlog clearing (P4–P7)

### LLM adapter timeout and retry (P4)

- **HTTP timeout and retry/backoff**:
  All LLM adapters (OpenAI, Anthropic, Gemini) now use a shared
  `_urlopen_with_retry()` helper with 60s default timeout and exponential
  backoff for transient HTTP errors (429, 500, 502, 503, 504).
  Default: 2 retries starting at 1s delay.

- **8 new retry/timeout tests** in `test_openai_adapter.py`:
  429/503 retry, retry exhaustion, no-retry on 400/401, timeout forwarding,
  default timeout, exponential backoff delay verification.

### Procedural memory tests (P4)

- **`test_procedural_memory.py`** — 6 tests covering the in-memory stub:
  initial empty read, write/read roundtrip, write replacement, read-returns-copy,
  write-stores-copy, context-ignored.

### Housekeeping (P5)

- **Removed 4 stale TODOs**: Deleted resolved TODO comments in `resume.py`
  (circular branching — already implemented), `llm/adapters.py`
  (`test_openai_adapter.py` — already exists), `llm/handler.py`
  (`test_llm_handler.py` and `05_llm_call.yaml` — both exist).

- **Deleted `agent-one/` directory**: Orphan scaffold with no imports or references.

- **Deleted stale `.pyc`**: Removed `handler_discovery.cpython-314.pyc` left behind
  after `handler_discovery.py` was deleted in P1.

- **Fixed stale doc references**:
  - `docs/about/status_2026-03-17.md`: Removed `handler_discovery.py` from module
    inventory, updated `ai init` scaffold description (removed `handlers/`),
    added `function_resolver.py` to module table.
  - `docs/about/architecture.md`: Removed `handlers:` from legacy manifest example,
    replaced "Handler auto-discovery" with "Function resolution" in status table.
  - `docs/guide/knowledge-base.md`: Rewrote "How They Tie Together" section for
    agent/function/tool step types, removed handler-centric examples, updated
    visual summary diagram.

- **Regenerated `docs/site/content.js`** from updated source markdown.

### Packaging (P6)

- **pyproject.toml metadata**:
  Added `authors` field, Python 3.14 classifier, `Homepage` and `Issues` URLs.

- **Ruff linter config**:
  Added `[tool.ruff]` and `[tool.ruff.lint]` sections: target Python 3.10,
  120-char line length, enabled E/F/W/I/UP/B/SIM rule sets.

### Feature gap TODOs (P7)

- **Gap 1** (LLM quickstart): Added TODO in `cli.py` `_init_project()` to
  scaffold a working LLM workflow by default.
- **Gap 7** (Richer expressions): Added TODO in `utils.py` `safe_eval()` to
  expand branch condition language with string methods, math helpers, and
  membership tests.

### Test count

- **448 passed, 0 failed** (up from 434 before backlog clearing).
