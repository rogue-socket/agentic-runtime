# Bug Fix & Code Quality Roadmap

> Generated from the full source audit (2026-04-25).
> **All 34 items fixed on 2026-04-25.** 635 tests passing, zero `BUG(...)` annotations remain.
> Kept as a record of what was found and fixed. Future audits (via `/audit`) should append below.

---

## P0 — Security (fix before any public/shared deployment)

### 1. DNS rebinding SSRF in HTTP tool
- **File:** `tools/http.py:65`
- **Issue:** `_is_private_host()` resolves the hostname once for validation, then `urllib.request.urlopen()` resolves it again independently. An attacker-controlled DNS server can return a public IP for the first lookup (passing the SSRF check) and a private IP for the second (hitting internal services).
- **Fix:** Resolve DNS once, validate the resolved IP, then connect directly to that IP (set `Host` header manually). Alternatively, use a custom `urllib` opener that hooks into the socket layer to enforce the check at connect time.
- **Effort:** Medium — requires replacing the simple `urlopen` call with a custom socket-level handler.

### 2. FTS5 query injection in semantic memory
- **File:** `memory/semantic.py:282`
- **Issue:** User-supplied search tokens are interpolated into an FTS5 MATCH expression using `f'"{t}"*'`. If a token contains a double quote, it breaks or manipulates the MATCH expression.
- **Fix:** Escape double quotes in tokens (`t.replace('"', '""')`) before interpolation.
- **Effort:** Small — one-line fix.

### 3. Shell denylist bypass via `&` and wrapper commands
- **File:** `tools/shell.py:94`
- **Issue:** `_extract_programs()` does not split on `&` (background operator). A command like `echo hello & rm -rf /` only extracts `echo`, so `rm` runs unchecked. Similarly, wrapper commands (`env`, `sudo`, `bash -c`, `xargs`) are not detected — `sudo rm -rf /` passes if only `sudo` is allowlisted.
- **Fix:** Add `&` to the split regex. For wrapper commands, either maintain a list of known wrappers and extract their sub-arguments, or document the limitation clearly and recommend denylist-only policies that include wrappers.
- **Effort:** Medium — `&` split is trivial, wrapper detection is design work.

### 4. Arbitrary code loading via custom strategy handler
- **File:** `agent/strategies.py:845`
- **Issue:** `_load_custom_strategy()` calls `importlib.import_module()` on a dotted path from workflow YAML. Any importable module's top-level code executes. A malicious YAML could point to a hostile package.
- **Fix:** Restrict to a known package prefix (e.g., only allow paths under the project's `functions/` or `strategies/` directory), or require strategies to be pre-registered in an allowlist.
- **Effort:** Medium — needs a design decision on how restrictive to be.

---

## P1 — Correctness (wrong behavior, data loss, or silent failures)

### 5. `state_before` overwritten on retry
- **File:** `core.py:814`
- **Issue:** On retry, `state_before` is set to the current state snapshot, overwriting the original pre-step state. After a failure + retry, the persisted `state_before` reflects the post-failure state, not the actual state when the step first began. This breaks `replay --verify-state`.
- **Fix:** Only capture `state_before` on `attempt == 1`. Guard with `if attempt_count == 1:` before the snapshot.
- **Effort:** Small.

### 6. Error truthiness check drops empty-string errors
- **File:** `core.py:561`
- **Issue:** `if error:` treats `""` as no error, but an empty string is a valid (if unhelpful) error value. Steps that fail with `error=""` are silently treated as successful.
- **Fix:** Change to `if error is not None:`.
- **Effort:** Small.

### 7. `timeout=0` silently becomes 30s in HTTP tool
- **File:** `tools/http.py:148`
- **Issue:** `self.timeout or 30` treats `0` as falsy. A user setting `timeout: 0` (meaning no timeout / immediate) gets 30 seconds instead.
- **Fix:** `self.timeout if self.timeout is not None else 30`.
- **Effort:** Small.

### 8. Wrong exception type in resume branch resolution
- **File:** `resume.py:147`
- **Issue:** Raises generic `ValueError` when it should raise `BranchResolutionError` to match the exception hierarchy used elsewhere in the executor.
- **Fix:** `raise BranchResolutionError(...)`.
- **Effort:** Small.

### 9. `to_dict()` drops `auto_tool_prompt` field
- **File:** `agent/definition.py:189`
- **Issue:** `AgentDefinition.to_dict()` does not include `auto_tool_prompt`. Round-tripping an agent definition through `to_dict()` / `load_agent_definition()` loses this setting, defaulting back to `True`.
- **Fix:** Add `"auto_tool_prompt": self.auto_tool_prompt` to the serialized dict.
- **Effort:** Small.

### 10. `pop()` mutates caller's dict in Anthropic adapter
- **File:** `llm/adapters.py:461`
- **Issue:** `params.pop("max_tokens", 4096)` mutates the caller's params dict. OpenAI and Gemini adapters use `.get()` — this one should too.
- **Fix:** Change `pop` to `get`.
- **Effort:** Small.

### 11. `close()` not thread-safe in SQLite storage
- **File:** `storage/sqlite.py:172`
- **Issue:** `close()` does not acquire `self._lock`. A concurrent thread could be mid-query when the connection is closed underneath it.
- **Fix:** Wrap the close body in `with self._lock:`.
- **Effort:** Small.

### 12. `integer` type not validated
- **File:** `tools/validation.py:44`
- **Issue:** A field declared `"type": "integer"` in a tool's input schema silently accepts any value (strings, lists, etc.) because the validator has no case for it.
- **Fix:** Add the integer case: `if expected == "integer" and (isinstance(value, bool) or not isinstance(value, int)): raise ValueError(...)`.
- **Effort:** Small.

### 13. FIFO eviction labeled as LRU in LLM client
- **File:** `llm/client.py:205`
- **Issue:** Usage tracking evicts the first-inserted run_id (FIFO), not the least-recently-used. A long-running run inserted early gets evicted even if actively making calls, losing its budget enforcement.
- **Fix:** Use `collections.OrderedDict` and call `move_to_end(run_id)` on access for true LRU.
- **Effort:** Small.

### 14. Inconsistent return shape in episodic memory
- **File:** `memory/episodic.py:190`
- **Issue:** `recall()` uses an explicit column list (no `id`), but `recall_all()` uses `SELECT *` (includes `id`). Callers get different dict keys depending on which method they call.
- **Fix:** Use the same explicit column list in both methods.
- **Effort:** Small.

### 15. `MemoryManager.close()` doesn't isolate tier failures
- **File:** `memory/base.py:120`
- **Issue:** If an early tier's `close()` raises, subsequent tiers are never closed (resource leak).
- **Fix:** Wrap each `close_fn()` call in its own try/except, collect errors, and optionally raise after all tiers are closed.
- **Effort:** Small.

### 16. `save_golden()` doesn't create parent directories
- **File:** `replay.py:202`
- **Issue:** `open(path, "w")` raises `FileNotFoundError` if the parent directory doesn't exist. Compare with `debugger.py` which uses `.mkdir(parents=True, exist_ok=True)`.
- **Fix:** Add `pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)` before writing.
- **Effort:** Small.

---

## P2 — Code quality (not broken, but misleading or wasteful)

### 17. Dead code in tool retry loop
- **File:** `core.py:1187`
- **Issue:** Code after the retry `for` loop is unreachable — every path through the loop either returns or raises.
- **Fix:** Remove the dead code block or add a defensive `raise RuntimeError("unreachable")` for clarity.
- **Effort:** Small.

### 18. Dead code in `_urlopen_with_retry`
- **File:** `llm/adapters.py:119`
- **Issue:** The final `return` after the retry loop is unreachable — the loop always returns on success or raises on final failure.
- **Fix:** Remove or replace with an explicit unreachable assertion.
- **Effort:** Small.

### 19. Stale docstring on `LLMResponse.tool_calls`
- **File:** `llm/types.py:24`
- **Issue:** Docstring says the field is "always empty" but all three adapters populate it with native function calling results.
- **Fix:** Update the docstring to describe actual behavior.
- **Effort:** Small.

### 20. Misleading comment in core dispatch
- **File:** `core.py:326`
- **Issue:** Comment says all dispatch methods return the same shape, but agent/function return `(output, handler_ms, None)` while tool returns `(output, handler_ms, tool_duration_ms)`.
- **Fix:** Correct the comment.
- **Effort:** Small.

### 21. `timeout_ms` silently ignored for function steps
- **File:** `core.py:462`
- **Issue:** Function steps accept `timeout_ms` in their definition but the executor never enforces it (unlike agent/tool steps).
- **Fix:** Either enforce the timeout (wrap in `asyncio.wait_for`) or document that function steps don't support timeouts and reject the field during validation.
- **Effort:** Medium — design decision needed.

### 22. Overly broad exception catch in replay branch coverage
- **File:** `replay.py:343`
- **Issue:** `except (ValueError, Exception)` — `Exception` subsumes `ValueError`, making the tuple redundant. More importantly, it silently swallows ALL exceptions including storage corruption.
- **Fix:** Catch only expected exceptions (`ValueError`, `KeyError`). Log unexpected ones.
- **Effort:** Small.

### 23. Duplicated code in `search_by_tags`
- **File:** `memory/semantic.py:318`
- **Issue:** The `match_all` and `match_any` branches have identical loop bodies — only the join operator (`AND` vs `OR`) differs.
- **Fix:** Extract the tag-escaping loop into a helper, parameterize the join operator.
- **Effort:** Small.

### 24. Complex ternary in observability
- **File:** `observability.py:138`
- **Issue:** Deeply nested inline expression for extracting model name from legacy trace entries. Hard to read and maintain.
- **Fix:** Extract into a local variable with clear intermediate steps.
- **Effort:** Small.

### 25. Percentile docstring mismatch
- **File:** `observability.py:50`
- **Issue:** Docstring says "nearest-rank interpolation" but implementation uses linear interpolation.
- **Fix:** Update docstring to say "linear interpolation".
- **Effort:** Small.

### 26. Unicode encoding assumption in HTML renderer
- **File:** `visualization/html_renderer.py:192`
- **Issue:** `f"_x{ord(ch):02X}_"` assumes characters fit in 2 hex digits. Unicode chars with `ord > 0xFF` produce 3+ hex digits (e.g., `_x1F4A9_`), which is inconsistent with the `02X` format hint but technically still works. The real risk is ambiguous round-tripping if a decoder assumes exactly 2 hex chars.
- **Fix:** Use `04X` for consistent 4-digit hex, or document the variable-width encoding.
- **Effort:** Small.

### 27. Broken doctest in ASCII renderer
- **File:** `visualization/ascii_renderer.py:39`
- **Issue:** `GraphView([], [], [])` and `TimelineView({}, [], {})` don't match the actual constructor signatures of these dataclasses.
- **Fix:** Update the doctest to use keyword arguments matching the current dataclass fields.
- **Effort:** Small.

### 28. `history` type annotation too narrow
- **File:** `llm/client.py:72`
- **Issue:** `List[Dict[str, str]]` but history entries contain non-string values (tool_calls lists, structured content).
- **Fix:** Change to `List[Dict[str, Any]]`.
- **Effort:** Small.

### 29. `list_runs` return type annotation missing
- **File:** `storage/sqlite.py:535`
- **Issue:** Return type is `list` instead of `list[Run]`. Also, `SELECT *` fetches the `metadata` column but `Run()` construction below doesn't use it.
- **Fix:** Annotate as `list[Run]` and either use or explicitly drop the metadata column.
- **Effort:** Small.

### 30. Unreachable fallback key in debugger
- **File:** `debugger.py:39`
- **Issue:** `payload.get("pipeline_step_id")` is never hit because the executor always emits `"agent_pipeline_step"`.
- **Fix:** Remove the fallback or add a comment explaining it's for backward compat with older persisted data.
- **Effort:** Small.

### 31. Unused imports
- **Files:** `cli.py:54` (`StepStatus`), `tools/discovery.py:4` (`inspect`)
- **Fix:** Remove unused imports.
- **Effort:** Small.

### 32. Unused `context` parameter in memory tiers
- **Files:** `memory/working.py:59`, `memory/procedural.py:70`
- **Issue:** `context` parameter accepted for protocol conformance but never read.
- **Fix:** No code change needed — this is by-design for the `MemoryTier` protocol. The annotation is informational. If the protocol is ever formalized, consider making `context` optional.
- **Effort:** None (informational).

### 33. Fragile truthiness check in config
- **File:** `config.py:202`
- **Issue:** Whitespace-only string `"  "` passes the truthiness check for `default_llm_provider`.
- **Fix:** Use `.strip()` before the check, or validate with an explicit `is not None and len(x.strip()) > 0`.
- **Effort:** Small.

### 34. Silent data overwrite in RuntimeState
- **File:** `state.py:119`
- **Issue:** `set("a.b", val)` silently replaces an existing non-dict value at `"a"` with `{}` when `create=True`. No warning emitted.
- **Fix:** Log a warning when overwriting a non-dict intermediate value so developers can detect unintended state corruption during debugging.
- **Effort:** Small.

---

## Execution Plan

All phases completed on 2026-04-25. 635 tests passing.

| Phase | Items | Status |
|-------|-------|--------|
| Phase 1 — Security hardening | 1-4 | Done |
| Phase 2 — Correctness sweep | 5-16 | Done |
| Phase 3 — Code quality cleanup | 17-34 | Done |
