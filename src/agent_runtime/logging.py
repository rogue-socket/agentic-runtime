from __future__ import annotations

"""File: src/agent_runtime/logging.py

Purpose:
Provide lightweight structured logging for runtime/tool events.

Description:
Defines a minimal JSON-lines logger used by execution flows to emit
machine-readable records suitable for debugging and audit trails.

Key Components:
- `StructuredLogger` with `info`, `error`, and dataclass support

Dependencies:
- `json`, `sys`, `dataclasses.asdict`

Inputs/Outputs:
- Input: event name plus payload
- Output: one JSON line per log call

Side Effects:
- Writes to configured stream (stdout by default).
"""

from dataclasses import asdict
from typing import Any, Dict
import json
import sys


_LEVELS = {"debug": 0, "info": 1, "warning": 2, "error": 3}


class StructuredLogger:
    """Emit structured JSON event logs.

    This logger intentionally keeps interface small so runtime modules
    can emit stable events without coupling to a heavy logging framework.

    TODO(roadmap): Add OpenTelemetry trace/span export so runtime events
      can be visualized in Jaeger, Grafana, Datadog, etc. Each run should
      be a trace, each step a span, with LLM calls as child spans.
    TODO(roadmap): Add optional webhook/callback event sink so external
      systems can subscribe to execution events in real time.
    TODO(roadmap): Emit Prometheus-compatible metrics (run count, step
      duration histograms, error rates, LLM token usage) for production
      monitoring dashboards.

    Example:
        >>> logger = StructuredLogger()
        >>> logger.info("RUN_START", {"run_id": "r1"})
    """

    def __init__(self, stream=None, level: str = "info") -> None:
        """Initialize logger with optional stream override.

        Args:
            stream: Writable text stream; defaults to `sys.stdout`.
            level: Minimum log level (debug/info/warning/error).

        Example:
            >>> StructuredLogger(stream=sys.stdout)
            <agent_runtime.logging.StructuredLogger object...>
        """
        self.stream = stream or sys.stdout
        self._level = _LEVELS.get(level, 1)

    def _emit(self, level: int, event: str, payload: Dict[str, Any]) -> None:
        if level < self._level:
            return
        record = {"event": event, **payload}
        self.stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    def info(self, event: str, payload: Dict[str, Any]) -> None:
        """Write an informational event as one JSON line.

        Args:
            event: Short event name.
            payload: Event-specific structured fields.

        Example:
            >>> StructuredLogger().info("STEP", {"id": "a"})
        """
        self._emit(1, event, payload)

    def error(self, event: str, payload: Dict[str, Any]) -> None:
        """Write an error event as one JSON line.

        Args:
            event: Error event name.
            payload: Structured error context.

        Example:
            >>> StructuredLogger().error("STEP_ERROR", {"id": "a"})
        """
        self._emit(3, event, payload)

    def from_dataclass(self, event: str, obj: Any) -> None:
        """Serialize a dataclass object and emit it as an info event.

        Args:
            event: Event name.
            obj: Dataclass instance convertible via `asdict`.

        Example:
            >>> from dataclasses import dataclass
            >>> @dataclass
            ... class P: x: int
            >>> StructuredLogger().from_dataclass("P", P(1))
        """
        self.info(event, asdict(obj))
