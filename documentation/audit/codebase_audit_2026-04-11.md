# Codebase Audit Report — agentic-runtime

**Date:** 2026-04-11  
**Scope:** Full codebase — source, tests, configuration, workflows, agents

---

## Summary

| Severity | Count |
|----------|-------|
| Critical / Security | 7 |
| Bugs | 9 |
| Configuration / Build | 5 |
| Dead / Unnecessary Code | 8 |
| Workflow / Agent YAML | 5 |
| Thread Safety / Resource Leaks | 5 |
| Minor / Code Quality | 9 |
| **Total** | **48** |

---

## 1. Critical / Security Issues

### 1.1 ShellTool denylist bypass via background operator `&`

**File:** `src/agent_runtime/tools/shell.py` L98  
**Severity:** Critical

`_extract_programs` splits commands on `|`, `||`, `&&`, `;`, and `\n` but does **not** split on `&` (the shell background operator). An attacker can chain a denied command after `&` and it passes the denylist check:

```python
# shell.py L98
segments = re.split(r'\|{1,2}|&&|;|\n', command)
```

**Exploit example:**
```
echo hello & rm -rf /
```
Only `echo` is extracted and checked. `rm` executes unchecked in the background.

**Fix:** Add `&` (single ampersand, word-boundary-aware) to the split pattern:
```python
segments = re.split(r'\|{1,2}|&&|&|;|\n', command)
```
Note: The `&` must come *after* `&&` in the alternation to avoid matching the first char of `&&`.

---

### 1.2 ShellTool denylist bypass via command wrappers

**File:** `src/agent_runtime/tools/shell.py` L115–128  
**Severity:** Critical

The denylist only checks the first token (program name) of each pipe/chain segment. Shell wrappers that execute other commands as arguments are not detected:

```
env rm -rf /        → denylist sees "env"
xargs rm            → denylist sees "xargs"
bash -c "rm -rf /"  → denylist sees "bash"
nice rm -rf /       → denylist sees "nice"
nohup rm -rf /      → denylist sees "nohup"
```

**Fix:** Maintain an additional list of known "wrapper" commands (`env`, `xargs`, `bash`, `sh`, `nohup`, `nice`, `sudo`, `su`, `strace`, `ltrace`, `time`, `exec`) and, when one is detected as the first token, also check the subsequent tokens against the denylist.

---

### 1.3 HTTP Tool DNS rebinding SSRF bypass

**File:** `src/agent_runtime/tools/http.py` L63–72, L139  
**Severity:** High

The SSRF protection performs DNS resolution in `_is_private_host()` (L63–72) *before* `urllib.request.urlopen()` (L139) performs its own independent DNS resolution. An attacker controlling their DNS server can return a public IP on the first lookup and `169.254.169.254` (or `127.0.0.1`, `10.x.x.x`) on the second:

```python
# L63-72: First DNS lookup - checks resolved IPs
def _is_private_host(hostname: str) -> bool:
    addrs = _resolve_host_addresses(hostname)
    ...

# L139: Second DNS lookup - connects to potentially different IP
with urllib.request.urlopen(req, timeout=self.timeout or 30) as resp:
```

**Fix:** Resolve DNS once, then connect directly to the resolved IP using a custom `urllib` opener that pins the socket address. Alternatively, resolve once and set the `Host` header while connecting to the IP.

---

### 1.4 Arbitrary code loading via `custom_handler`

**File:** `src/agent_runtime/agent/strategies.py` L842–856  
**Severity:** High

`_load_custom_strategy` calls `importlib.import_module` on any dotted path specified in agent YAML with no allowlist, no sandbox, and no namespace restriction:

```python
# strategies.py L842-852
def _load_custom_strategy(dotted_path: str) -> AgentStrategyProtocol:
    module_path, _, class_name = dotted_path.rpartition(".")
    ...
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name, None)
    return cls()
```

An attacker who can write or modify agent YAML can supply `custom_handler: "os.system"` or point to any arbitrary module, achieving arbitrary code execution.

**Fix:** Restrict `module_path` to a known namespace (e.g., must start with `agent_runtime.strategies.` or be within a specified plugins directory). Reject paths containing `os`, `sys`, `subprocess`, `shutil`, `importlib` etc.

---

### 1.5 FTS5 query injection in semantic memory search

**File:** `src/agent_runtime/memory/semantic.py` L282–285  
**Severity:** High

User-supplied search tokens are wrapped in double quotes for FTS5 MATCH but embedded quote characters are never escaped:

```python
# semantic.py L282-285
tokens = query.strip().split()
match_expr = " ".join(f'"{t}"*' for t in tokens)
```

A query like `my "test` produces the malformed expression `"my"* ""test"*`, which either causes `sqlite3.OperationalError` or alters query semantics with FTS5 operators (`AND`, `OR`, `NOT`, `NEAR`).

**Fix:** Strip or escape double quotes from each token before interpolation:
```python
tokens = [t.replace('"', '') for t in query.strip().split()]
```

---

### 1.6 ReDoS via `output_schema.regex`

**File:** `src/agent_runtime/core.py` L1279  
**Severity:** High

The `output_schema` in workflow YAML accepts a `regex` key. The pattern is run through `re.fullmatch()` with no complexity guard or timeout:

```python
# core.py L1279
if not isinstance(value, str) or not _re.fullmatch(pattern, value):
```

A workflow author can supply a catastrophic backtracking pattern like `(a+)+$` that causes exponential CPU time on crafted step output.

**Fix:** Compile the regex with `re.compile()` and set a timeout (Python 3.12+ `re.TIMEOUT`), or pre-validate the pattern complexity using a library like `rxxr2` / `safe-regex`.

---

### 1.7 `tar.extractall()` without `filter` parameter

**File:** `src/agent_runtime/cli.py` L206  
**Severity:** Medium

```python
# cli.py L206
tar.extractall(path=target_dir)
```

While the code has manual member traversal checks above (symlink resolution, path prefix checks), the `filter` parameter is not used. Python 3.12 deprecated calling `extractall()` without `filter`, and Python 3.14 changes the default behavior. The `filter='data'` option also handles additional attack vectors like special device files on Unix.

**Fix:**
```python
tar.extractall(path=target_dir, filter='data')
```

---

## 2. Bugs

### 2.1 `timeout_ms` silently ignored for function steps

**File:** `src/agent_runtime/core.py` L435–450  
**Severity:** High

`_dispatch_function` is synchronous and never checks `timeout_ms`. Compare with `_dispatch_agent` and `_dispatch_tool` which both route through `_run_with_timeout_and_heartbeat`:

```python
# core.py L435-450
def _dispatch_function(self, step_def, step_input, snapshot):
    func_input = step_input if step_def.input_spec is not None else snapshot
    ...
    output = step_def.function_callable(func_input)  # blocks forever if func hangs
    handler_duration_ms = int((time.monotonic() - call_start) * 1000)
    return output, handler_duration_ms, None
```

Additionally, because this is synchronous, it blocks the asyncio event loop, halting heartbeat events for the duration.

**Impact:** A user setting `timeout_ms: 5000` on a function step gets zero timeout enforcement. A hanging function stalls the entire runtime.

---

### 2.2 `state_before` corrupted on retry

**File:** `src/agent_runtime/core.py` L789–790  
**Severity:** High

Inside the retry loop, `execution.state_before` is unconditionally overwritten on each attempt:

```python
# core.py L789-790
for attempt in range(1, max_attempts + 1):
    snapshot = run.state.snapshot()
    execution.state_before = copy.deepcopy(snapshot)
```

If attempt 1 fails (potentially mutating state via memory hydration or side effects), attempt 2's `state_before` reflects the post-failure state — not the original state before any attempts. This corrupts replay/diff features that depend on `state_before` accuracy.

**Fix:** Capture `state_before` once, before the retry loop begins.

---

### 2.3 `SQLiteStorage.close()` skips lock

**File:** `src/agent_runtime/storage/sqlite.py` L149–160  
**Severity:** Medium

```python
# sqlite.py L149-160
def close(self) -> None:
    if self._conn is not None:
        try:
            self._conn.close()
        except Exception:
            pass
        self._conn = None
```

`close()` does not acquire `self._lock`. A concurrent thread could pass `_check_open()` and begin executing SQL, then `close()` sets `_conn = None` mid-execution, causing `AttributeError`.

**Fix:** Wrap `close()` body in `with self._lock:`.

---

### 2.4 `MemoryManager.close()` doesn't isolate tier failures

**File:** `src/agent_runtime/memory/base.py` L106–111  
**Severity:** Medium

```python
# base.py L106-111
def close(self) -> None:
    for _name, tier in self._tiers():
        close_fn = getattr(tier, "close", None)
        if callable(close_fn):
            close_fn()
```

If the first tier's `close()` raises an exception, remaining tiers are never closed, leaking their SQLite connections.

**Fix:** Wrap each `close_fn()` call in `try/except`, collect errors, and optionally raise an aggregate at the end.

---

### 2.5 LLM budget eviction is FIFO, not LRU

**File:** `src/agent_runtime/llm/client.py` L174–182  
**Severity:** Medium

```python
# client.py L180-182
if len(self._run_usage) >= self._max_tracked_runs:
    oldest_key = next(iter(self._run_usage))
    del self._run_usage[oldest_key]
```

This evicts the first-inserted key (FIFO), not the least-recently-used. An active long-running run that was started first will have its budget tracking evicted and reset, allowing it to silently **exceed its cost/token limits**.

**Fix:** Use `collections.OrderedDict` with `move_to_end()` on access, or track a `last_accessed` timestamp.

---

### 2.6 `AnthropicAdapter.call()` mutates caller's parameters dict

**File:** `src/agent_runtime/llm/adapters.py` L484  
**Severity:** Medium

```python
# adapters.py L484
"max_tokens": params.pop("max_tokens", 4096),
```

`params.pop()` modifies the input dict in-place. While `LLMClient.call()` creates a `merged_params` copy, any direct caller of the adapter would have their dict silently modified — unlike the OpenAI and Gemini adapters which only read params.

**Fix:** Use `params.get("max_tokens", 4096)` instead of `pop`.

---

### 2.7 Only first failed step is resumed

**File:** `src/agent_runtime/resume.py` L41–56  
**Severity:** Medium

```python
# resume.py L53-56
for execution in executions:
    if execution.status == StepStatus.FAILED:
        _validate_failed_step_resume(execution, step_map, resolved_policy)
        return execution.step_id
```

In `on_error: continue` mode, multiple steps can fail. This always returns the first failure and silently ignores subsequent ones. Users may think resume fixed all failures when it only re-ran the first.

**Fix:** Return a list of all failed step IDs, or add a `resume_all` mode.

---

### 2.8 HTTP timeout `or 30` treats `0.0` as falsy

**File:** `src/agent_runtime/tools/http.py` L139  
**Severity:** Low

```python
# http.py L139
with urllib.request.urlopen(req, timeout=self.timeout or 30) as resp:
```

If `self.timeout` is explicitly set to `0` or `0.0`, the `or` expression evaluates to `30` instead. This silently overrides the caller's intent.

**Fix:** Use `self.timeout if self.timeout is not None else 30`.

---

### 2.9 `"integer"` JSON Schema type not handled in validation

**File:** `src/agent_runtime/tools/validation.py` L30–41  
**Severity:** Low

The type validation logic handles `string`, `number`, `boolean`, `object`, `array` but not `integer`:

```python
# validation.py L30-41
if expected == "string" and not isinstance(value, str): ...
if expected == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))): ...
if expected == "boolean" and not isinstance(value, bool): ...
if expected == "object" and not isinstance(value, dict): ...
if expected == "array" and not isinstance(value, list): ...
# No handler for "integer"
```

A field declared `"type": "integer"` silently accepts any value (strings, lists, etc.).

**Fix:** Add `if expected == "integer" and (isinstance(value, bool) or not isinstance(value, int)):`.

---

## 3. Configuration / Build Issues

### 3.1 `requirements.txt` has no version pinning

**File:** `requirements.txt`  
**Severity:** Medium

All packages listed without version constraints (`PyYAML`, `pytest`, etc.), while `pyproject.toml` specifies minimums (`PyYAML>=6.0`, `pytest>=7.0`). Running `pip install -r requirements.txt` can install incompatible older versions.

**Fix:** Pin to match `pyproject.toml` minimums or, better, generate a lockfile.

---

### 3.2 `ruff` not in dev dependencies

**File:** `pyproject.toml`  
**Severity:** Low

`[tool.ruff]` is configured with rules and settings, but `ruff` is not listed in `[project.optional-dependencies] dev`. A developer following `pip install -e ".[dev]"` won't get ruff installed.

**Fix:** Add `"ruff>=0.4"` (or appropriate version) to the `dev` dependencies list.

---

### 3.3 Stale egg-info tracked in git

**File:** `src/agentic_runtime.egg-info/`  
**Severity:** Low

Despite `.gitignore` containing `*.egg-info/`, this directory is tracked (committed before the rule was added). It contains:
- **Version mismatch:** `PKG-INFO` says `0.1.0`, `pyproject.toml` says `0.1.2`
- **Ghost files in `SOURCES.txt`:** References `steps.py`, `handler.py`, `manifest.py`, `packaging.py` — none exist on disk
- **Missing files from `SOURCES.txt`:** `debugger.py`, `observability.py`, `schema_versioning.py` not listed

**Fix:** Run `git rm -r --cached src/agentic_runtime.egg-info/` to untrack. The existing `.gitignore` rule prevents re-addition.

---

### 3.4 Invalid YAML config silently returns defaults

**File:** `src/agent_runtime/config.py` L127–128  
**Severity:** Medium

```python
# config.py L127-128
if not isinstance(raw, dict):
    return cfg
```

If `runtime.yaml` contains a bare string, list, or `---null`, the loader silently returns default config with no warning. Users can spend significant time debugging missing settings.

**Fix:** Log a warning when `raw` is not a dict, e.g. `logger.warning("runtime.yaml content is not a mapping; using defaults")`.

---

### 3.5 No validation of `log_level` / `log_format` config values

**File:** `src/agent_runtime/config.py` L78–79  
**Severity:** Low

Invalid values like `log_level: super_verbose` are silently accepted. `StructuredLogger.__init__` falls back to level 1 for unknown levels, effectively ignoring the setting without feedback.

**Fix:** Validate against a set of known levels (`debug`, `info`, `warning`, `error`) and raise or warn on invalid values.

---

## 4. Dead / Unnecessary Code

### 4.1 ~600 lines of analytics embedded in SQLiteStorage

**File:** `src/agent_runtime/storage/sqlite.py` L545+  
**Severity:** Medium (maintenance burden)

The following methods belong in a separate analytics/reporting module, not in the storage CRUD class:
- `_parse_iso_timestamp`, `_pick_metadata_value`, `_parse_bool`, `_parse_confidence`
- `_extract_confidence_values`, `_extract_step_meta`, `_classify_input`
- `_compute_ece`, `_safe_rate`, `_score_latency`
- `build_observability_report` (~500 lines)
- `_HEALTH_WEIGHTS` module-level dict

This violates single-responsibility. The `yaml` import (L30) exists solely for this analytics code.

---

### 4.2 Unused imports in `__init__.py`

**File:** `src/agent_runtime/__init__.py` L24–25  
**Severity:** Low

```python
import asyncio  # never used
import os        # never used
```

Dead imports increase package import time.

---

### 4.3 Unused `import inspect` in discovery.py

**File:** `src/agent_runtime/tools/discovery.py` L4  
**Severity:** Low

```python
import inspect  # never referenced
```

---

### 4.4 Redundant `ToolDiscovery` class

**File:** `src/agent_runtime/tools/discovery.py` L38–53  
**Severity:** Low

The `ToolDiscovery` class is a thin wrapper around the module-level `_discover_tool_instances()` function. The runtime uses the standalone `discover_tools()` function; the class adds no value.

---

### 4.5 Unreachable `10**9` sort fallback

**File:** `src/agent_runtime/visualization/graph_builder.py` L120  
**Severity:** Low

```python
nodes.sort(key=lambda n: (
    (n.execution_index is None),
    n.execution_index if n.execution_index is not None else 10**9,
    n.step_id
))
```

When `execution_index is None`, the first tuple element is `True` (sorts last). The `10**9` fallback is only evaluated for those same `None` entries, but they're already grouped at the end — making the value meaningless. Could be `0` or any value.

---

### 4.6 Redundant `except (ValueError, Exception)` in replay.py

**File:** `src/agent_runtime/replay.py` L340  
**Severity:** Low

```python
except (ValueError, Exception):
    continue
```

`Exception` already subsumes `ValueError`. More importantly, this silently swallows **all** exceptions during step loading, including storage corruption errors that should surface.

---

### 4.7 Cost estimation ignores model-specific pricing

**File:** `src/agent_runtime/cli.py` L209–232  
**Severity:** Low

The docstring says "tries provider/model-specific pricing first, then `*` wildcard" but the implementation only checks `pricing.get("*")`. Model-specific pricing entries are never consulted.

---

### 4.8 Dead `count_actions` step output in research.yaml

**File:** `workflows/research.yaml` L27–31  
**Severity:** Low

The `count_actions` function step produces `action_count` and `status`, but no subsequent step (`format` or `echo_brief`) references these values. The step executes but its output is never consumed.

---

## 5. Workflow / Agent YAML Issues

### 5.1 Unregistered tools in example.yaml

**File:** `workflows/example.yaml`  
**Severity:** High

Steps `priority` and `build_report` reference `tools.priority_heuristic` and `tools.report_builder`. The classes `PriorityHeuristicTool` and `ReportBuilderTool` exist in `cli.py` (L488, L539) but `_default_tool_registry()` (L1521) never instantiates or registers them. Running this workflow fails at runtime with tool-not-found errors.

**Fix:** Either register these tools in `_default_tool_registry()`, or move the class definitions to separate files under `tools/` where they can be auto-discovered.

---

### 5.2 Pipeline references non-existent model output field

**File:** `agents/code_reviewer.yaml` L22  
**Severity:** Medium

The `fetch_context` pipeline step has `path: analyze.suggested_file`. The `analyze` step is `type: model`, which produces a `text` field from the LLM response. There is no guaranteed `suggested_file` key in model output. This dot-path resolution will resolve to `None` or fail at runtime.

---

### 5.3 Unused tool declaration in code_reviewer.yaml

**File:** `agents/code_reviewer.yaml` L8  
**Severity:** Low

The agent's `tools` list includes `tools.http`, but the pipeline's only tool step (`fetch_context`) uses `tools.file`. The `tools.http` declaration is dead config.

---

### 5.4 Duplicate prompts across files

**File:** `agents/code_reviewer.yaml` L29–45, `prompts/code_review.yaml`  
**Severity:** Low

Inline prompts with `id: code_review_system` duplicate the identical content in the external `prompts/code_review.yaml` file. Having two sources of truth risks drift when one copy is updated but not the other.

---

### 5.5 `priority` input silently dropped by fixer agent

**File:** `agents/fixer.yaml` L17, `workflows/example.yaml` L35  
**Severity:** Low

The example workflow passes `priority: steps.priority.priority` to the fixer agent, but the fixer's prompt template only references `{{ inputs.issue }}` and `{{ inputs.summary }}`. Priority information is accepted but silently ignored.

---

## 6. Thread Safety / Resource Leaks

### 6.1 `StructuredLogger._emit` is not thread-safe

**File:** `src/agent_runtime/logging.py` L66–71  
**Severity:** Medium

```python
def _emit(self, level, event, payload):
    if level < self._level:
        return
    record = {"event": event, **payload}
    self.stream.write(json.dumps(record, ensure_ascii=False) + "\n")
```

No synchronization around `stream.write()`. Concurrent threads or async tasks calling `_emit` can interleave JSON lines, producing corrupted output.

**Fix:** Add a `threading.Lock` and acquire it around the `write` call.

---

### 6.2 Module name `logging.py` shadows stdlib

**File:** `src/agent_runtime/logging.py`  
**Severity:** Medium

The module name collides with Python's `logging`. While relative imports (`from .logging import ...`) work correctly, any absolute `import logging` inside the package gets this file instead of stdlib. The CLI works around this with `import logging as _logging` inside a function body, but this is fragile for future contributors.

**Fix:** Rename to `structured_logging.py` or `log.py`.

---

### 6.3 `build_observability_report` reads without lock

**File:** `src/agent_runtime/storage/sqlite.py` L727–740  
**Severity:** Medium

Multiple SQL queries are executed directly on `self._conn` without acquiring `self._lock`. Concurrent writes between these reads produce an inconsistent view of runs vs. steps.

**Fix:** Wrap all queries in the method inside `with self._lock:` or use a dedicated read transaction.

---

### 6.4 Memory tiers lack context-manager support

**Files:** `src/agent_runtime/memory/episodic.py`, `semantic.py`, `procedural.py`  
**Severity:** Low

None of `EpisodicMemory`, `SemanticMemory`, or `ProceduralMemory` implement `__enter__`/`__exit__`. If `close()` is never called (exception during setup, forgotten cleanup), SQLite connections leak. `SQLiteStorage` correctly implements context managers — these should too.

---

### 6.5 Test `make_storage()` leaks temp files

**File:** `tests/conftest.py` L19–23  
**Severity:** Low

```python
def make_storage() -> SQLiteStorage:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmp.close()
    return SQLiteStorage(tmp.name)
```

`delete=False` without any cleanup logic. Each test run leaves an orphaned `.db` file in the OS temp directory. Contrast with tests using `tmp_path` fixtures which self-clean.

**Fix:** Use `tmp_path` fixture or add an `atexit` / finalizer to remove the file.

---

## 7. Minor / Code Quality Issues

### 7.1 Overly aggressive number redaction in observability

**File:** `src/agent_runtime/observability.py` L20  
**Severity:** Low

```python
(re.compile(r"\b\d{13,19}\b"), "[REDACTED_NUMBER]"),
```

Matches any 13–19 digit number, including Unix millisecond timestamps (13 digits), database row IDs, and version hashes. Useful debug data is silently destroyed.

**Fix:** Narrow the pattern to match known PII formats (e.g., Luhn-checkable credit card patterns) rather than all long numbers.

---

### 7.2 Frozen `RunState.data` returns shallow copy

**File:** `src/agent_runtime/core.py` L85–89  
**Severity:** Low

```python
@property
def data(self) -> StateDict:
    current = self._runtime_state.to_dict()
    return dict(current) if self._frozen else current
```

When frozen, `dict()` makes a shallow copy — nested dicts are still shared references. Code assuming frozen data is immutable can experience subtle mutation bugs.

---

### 7.3 `StepStatus` is `str` subclass, not `Enum`

**File:** `src/agent_runtime/core.py` L55–62  
**Severity:** Low

`StepStatus("anything_at_all")` is valid. Throughout the codebase, comparisons use string literals (`== "COMPLETED"`) rather than the class constants, so the type provides no safety.

---

### 7.4 No progress events for function-step errors

**File:** `src/agent_runtime/core.py` L842–843  
**Severity:** Low

Error-phase progress events are only emitted for `agent`/`tool` step types:

```python
if step_def.step_type in {"agent", "tool"}:
    self._emit_step_progress(...)
```

Function-step failures are invisible to debugger/progress callbacks.

---

### 7.5 Duplicate edges for branch steps in graph builder

**File:** `src/agent_runtime/visualization/graph_builder.py` L85–89, L117–118  
**Severity:** Low

Steps with branch rules get both an `"executed"` edge (from sequential execution tracking) and a `"branch"` edge (from branch evaluation) for the same source→target pair, producing duplicate edges in the visualization.

---

### 7.6 Mixed indentation in html_renderer.py

**File:** `src/agent_runtime/visualization/html_renderer.py` L170–212  
**Severity:** Low

`_load_html_template` and `_build_mermaid_flow` use 2-space indentation, while the rest of the file uses 4-space. Valid Python but inconsistent.

---

### 7.7 `recall_all` vs `recall` return shape inconsistency

**File:** `src/agent_runtime/memory/episodic.py` L165–187  
**Severity:** Low

`recall()` uses explicit column names (no `id`), `recall_all()` uses `SELECT *` (includes `id`). The two methods return different shapes for the same data type.

---

### 7.8 Python 3.14 classifier is premature

**File:** `pyproject.toml` L26  
**Severity:** Trivial

`Programming Language :: Python :: 3.14` listed as a classifier. Python 3.14 is not released (scheduled Oct 2026).

---

### 7.9 Hardcoded test count badge in README

**File:** `README.md` L7  
**Severity:** Trivial

Static badge showing "448 passing". Will silently go stale as tests are added or removed.

---

### 7.10 `_init_project` creates invalid 0-byte SQLite file

**File:** `src/agent_runtime/cli.py` L769–772  
**Severity:** Low

```python
if not os.path.exists(runtime_db_path):
    with open(runtime_db_path, "a", encoding="utf-8"):
        pass
```

Creates an empty file, not a valid SQLite database. If read before `SQLiteStorage` initializes the schema, this causes `sqlite3.DatabaseError`.

**Fix:** Either let `SQLiteStorage` handle creation entirely, or use `sqlite3.connect(path)` to create a valid empty database.

---

### 7.11 `_build_tool_schemas` silently swallows tool resolution failures

**File:** `src/agent_runtime/agent/strategies.py` L278–279  
**Severity:** Low

```python
except Exception:  # noqa: BLE001
    pass
```

If a tool fails to resolve from the registry (typo, misconfiguration), it is silently dropped. The agent proceeds with a partial tool list and no diagnostic signal.

---

### 7.12 Debugger expression breakpoints silently swallow errors

**File:** `src/agent_runtime/debugger.py`  
**Severity:** Low

Invalid breakpoint expressions (syntax errors, non-existent state paths) silently return `False` rather than alerting the user. Two nested `try/except Exception: return False` blocks ensure the user never learns their breakpoint is broken.

---

### 7.13 `functions/pipeline.py` falsy check on numeric zero

**File:** `functions/pipeline.py` L52  
**Severity:** Low

```python
normalized = round(value / 100, 4) if value else 0
```

When `value` is `0` (a legitimate numeric value), the `if value` test is `False`, and `0` (int) is returned instead of `round(0/100, 4)` = `0.0` (float). The result is mathematically identical but the type is inconsistent, and the pattern would be a real bug for other operations (e.g., if the fallback were non-zero).

**Fix:** Use `if value is not None` instead of `if value`.

---

### 7.14 `LLMClient.call` history parameter has wrong type annotation

**File:** `src/agent_runtime/llm/client.py` L74  
**Severity:** Trivial

```python
history: Optional[List[Dict[str, str]]] = None,
```

Actual history dicts contain `Any` values (`_native_tool_calls`, `_native_results` are lists of dicts). Should be `Optional[List[Dict[str, Any]]]`.

---

### 7.15 ReAct pipeline state overwrite across iterations

**File:** `src/agent_runtime/agent/strategies.py` L636–731  
**Severity:** Low

The same `pipeline_state` dict is reused across ReAct iterations. Each iteration's step outputs overwrite previous iteration's values under the same step IDs. Previous iteration outputs are lost (only the `_history` list accumulates). Acknowledged by an inline TODO but remains a design-level issue for multi-step react pipelines.

---

## Prioritized Fix Recommendations

### Immediate (security-critical)
1. **Shell denylist bypass** (#1.1, #1.2) — Add `&` to split pattern; add wrapper-command detection
2. **SSRF DNS rebinding** (#1.3) — Pin DNS resolution
3. **Custom handler code load** (#1.4) — Add namespace allowlist
4. **FTS5 injection** (#1.5) — Escape/strip quotes from search tokens

### Short-term (correctness bugs)
5. **Function step timeout** (#2.1) — Wrap in `asyncio.to_thread` + `wait_for`
6. **State-before overwrite** (#2.2) — Capture once before retry loop
7. **SQLite close() locking** (#2.3) — Acquire lock in `close()`
8. **Memory close isolation** (#2.4) — Try/except per tier
9. **Register example tools** (#5.1) — Wire into `_default_tool_registry()`

### Medium-term (maintenance & quality)
10. **Extract analytics from SQLiteStorage** (#4.1)
11. **Rename `logging.py`** (#6.2)
12. **Align requirements.txt with pyproject.toml** (#3.1)
13. **Clean up dead code** (#4.2–4.8)
14. **Remove stale egg-info** (#3.3)
