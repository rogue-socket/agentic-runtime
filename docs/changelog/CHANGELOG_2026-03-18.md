# Changelog — 2026-03-18

## Features

- **End-to-end timing telemetry**:
  Per-step duration is now computed before event emission, and model/tool call
  latencies are captured (`handler_duration_ms`, `tool_duration_ms`) for each step.
  Run-level total duration is derived from run start/completion timestamps.

- **Visualization enhancements**:
  HTML/ASCII outputs now show run summary (start, completion, total duration)
  and per-step call durations. HTML tool tables include tool latency.

- **CLI progress output**:
  `ai run` step progress now prints `n/a` instead of `None` and includes call duration
  when available.

## UX

- **`ai visualize --html` auto-opens**:
  HTML visualization now opens the browser by default. Use `--no-open` to disable.

## Housekeeping

- **Ignore generated run artifacts**:
  Added `.runs/` to `.gitignore`.

## Documentation

- **Full documentation refresh** (all files updated to reflect 2026-03-18 codebase state):
  - `.copilot/instructions.md` — added pyproject.toml, security-sensitive areas (shell allowlist, symlink rejection), memory namespacing, lifecycle hooks, overwrite policy notes
  - `.copilot/project_context.md` — updated subsystem status table (17 → 18 entries), corrected packaging status, memory tier status (working + semantic now "Implemented")
  - `.copilot/session_state.md` — full rewrite for 2026-03-18 session with prior session summary
  - `.copilot/working_set.md` — updated focus area, file list, core files, test inventory (21 tests)
  - `.copilot/resume_prompt.md` — updated with 2026-03-18 state, 14 CLI commands, timing telemetry
  - `.copilot/architecture_decisions.md` — added ADR-011 (timing telemetry)
  - `.github/prompts/start-session.prompt.md` — updated doc references, added architecture rules
  - `docs/about/architecture.md` — updated memory subsystem (§8: working, semantic, episodic detail), config fields (§16: overwrite policy, memory limits, shell, LLM), added lifecycle hooks (§17) and timing telemetry (§18) sections, renumbered extensions/LLM to §19/§20
  - `docs/guide/onboarding-walkthrough.md` — fixed hardcoded absolute macOS path to relative `scripts/onboard.sh`
  - `docs/about/gaps_2026-03-17.md` — marked gaps 3 (memory), 5 (input coercion), 6 (security) as RESOLVED; gap 2 (streaming) as partially resolved
  - `docs/about/status_2026-03-17.md` — updated memory subsystem table, added 2026-03-18 visualization note
  - `docs/changelog/CHANGELOG_2026-03-18.md` — this file (expanded with documentation section)
