"""Server-Sent Events (SSE) parser for streaming LLM responses.

Uses stdlib urllib only — no external HTTP libraries.
"""

from __future__ import annotations
import json
from typing import Iterator, Dict, Any, Optional


def parse_sse_line(line: str) -> Optional[Dict[str, Any]]:
    """Parse a single SSE line into a data dict.

    SSE format:
        field: value
        :comment
        <blank line>

    Args:
        line: A single line from SSE stream (may be partial).

    Returns:
        Parsed event dict with 'event' and 'data' keys, or None if not a data line.
    """
    line = line.rstrip("\r\n")

    # Skip empty lines and comments
    if not line or line.startswith(":"):
        return None

    # Parse field: value format
    if ":" in line:
        field, _, value = line.partition(":")
        # Remove leading space from value if present
        if value.startswith(" "):
            value = value[1:]
        return {"field": field, "value": value}

    return None


def parse_sse_event(lines: list[str]) -> Optional[Dict[str, Any]]:
    """Parse multiple SSE lines into a complete event dict.

    Accumulates field:value pairs until a blank line is encountered.

    Note: Some providers (e.g., OpenAI) don't include "event:" fields.
    In that case, uses a default event name.

    Args:
        lines: List of SSE lines (from event boundary).

    Returns:
        Event dict with 'event' and 'data' keys, or None if incomplete.
    """
    event_type = None
    data_parts = []

    for line in lines:
        parsed = parse_sse_line(line)
        if parsed is None:
            continue

        if parsed["field"] == "event":
            event_type = parsed["value"]
        elif parsed["field"] == "data":
            data_parts.append(parsed["value"])

    # If no data, return None
    if not data_parts:
        return None

    # If no event type, default to "message" (for OpenAI-style SSE)
    if not event_type:
        event_type = "message"

    # Join data parts and parse as JSON
    data_str = "\n".join(data_parts)
    try:
        data = json.loads(data_str)
    except json.JSONDecodeError:
        # If not JSON, return as-is
        data = data_str

    return {"event": event_type, "data": data}


class SSEStreamParser:
    """Stateful parser for streaming SSE responses.

    Handles line buffering, incomplete chunks, and event boundaries.
    """

    def __init__(self, on_event: callable = None):
        """Initialize parser.

        Args:
            on_event: Optional callback(event_type, data) for each complete event.
        """
        self.on_event = on_event
        self.buffer = ""
        self.lines: list[str] = []

    def feed(self, chunk: str) -> Iterator[Dict[str, Any]]:
        """Feed a chunk of data and yield complete events.

        Args:
            chunk: Raw string data from streaming response.

        Yields:
            Complete event dicts {event: type, data: ...}
        """
        self.buffer += chunk
        lines = self.buffer.split("\n")

        # Keep the last incomplete line in buffer
        self.buffer = lines[-1]
        lines = lines[:-1]

        for line in lines:
            # Strip whitespace (including CRLF)
            line = line.rstrip("\r\n")

            if line == "":
                # Blank line marks event boundary
                if self.lines:
                    event = parse_sse_event(self.lines)
                    if event:
                        if self.on_event:
                            self.on_event(event["event"], event["data"])
                        yield event
                    self.lines = []
            else:
                self.lines.append(line)

    def flush(self) -> Iterator[Dict[str, Any]]:
        """Flush any remaining buffered data.

        Yields:
            Final complete events.
        """
        if self.buffer:
            # Process remaining buffer
            yield from self.feed("\n")

        # Process any remaining lines
        if self.lines:
            event = parse_sse_event(self.lines)
            if event:
                if self.on_event:
                    self.on_event(event["event"], event["data"])
                yield event
            self.lines = []
