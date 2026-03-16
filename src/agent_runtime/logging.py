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


class StructuredLogger:
    """Emit structured JSON event logs.

    This logger intentionally keeps interface small so runtime modules
    can emit stable events without coupling to a heavy logging framework.

    Example:
        >>> logger = StructuredLogger()
        >>> logger.info("RUN_START", {"run_id": "r1"})
    """

    def __init__(self, stream=None) -> None:
        """Initialize logger with optional stream override.

        Args:
            stream: Writable text stream; defaults to `sys.stdout`.

        Example:
            >>> StructuredLogger(stream=sys.stdout)
            <agent_runtime.logging.StructuredLogger object...>
        """
        self.stream = stream or sys.stdout

    def info(self, event: str, payload: Dict[str, Any]) -> None:
        """Write an informational event as one JSON line.

        Args:
            event: Short event name.
            payload: Event-specific structured fields.

        Example:
            >>> StructuredLogger().info("STEP", {"id": "a"})
        """
        record = {"event": event, **payload}
        self.stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    def error(self, event: str, payload: Dict[str, Any]) -> None:
        """Write an error event as one JSON line.

        Args:
            event: Error event name.
            payload: Structured error context.

        Example:
            >>> StructuredLogger().error("STEP_ERROR", {"id": "a"})
        """
        record = {"event": event, **payload}
        self.stream.write(json.dumps(record, ensure_ascii=False) + "\n")

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
