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
