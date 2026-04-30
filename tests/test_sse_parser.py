"""Tests for SSE (Server-Sent Events) parser."""

from __future__ import annotations
import json
import pytest
from agent_runtime.llm.sse import parse_sse_line, parse_sse_event, SSEStreamParser


class TestSSELineParsing:
    """Test parse_sse_line function."""

    def test_parse_data_line(self):
        """Parse data:value line."""
        result = parse_sse_line("data: {\"token\": \"hello\"}")
        assert result is not None
        assert result["field"] == "data"
        assert result["value"] == "{\"token\": \"hello\"}"

    def test_parse_event_line(self):
        """Parse event:type line."""
        result = parse_sse_line("event: content_block_delta")
        assert result is not None
        assert result["field"] == "event"
        assert result["value"] == "content_block_delta"

    def test_parse_line_without_space_after_colon(self):
        """Parse line without space after colon."""
        result = parse_sse_line("data:{\"key\": \"value\"}")
        assert result is not None
        assert result["value"] == "{\"key\": \"value\"}"

    def test_parse_empty_value(self):
        """Parse line with empty value."""
        result = parse_sse_line("data: ")
        assert result is not None
        assert result["field"] == "data"
        assert result["value"] == ""

    def test_parse_comment_line(self):
        """Skip comment lines."""
        result = parse_sse_line(":this is a comment")
        assert result is None

    def test_parse_empty_line(self):
        """Skip empty lines."""
        result = parse_sse_line("")
        assert result is None

    def test_parse_line_with_carriage_return(self):
        """Handle lines with CRLF."""
        result = parse_sse_line("data: hello\r\n")
        assert result is not None
        assert result["value"] == "hello"

    def test_parse_colon_in_value(self):
        """Handle colons in the value."""
        result = parse_sse_line("data: https://example.com:8080/path")
        assert result is not None
        assert result["value"] == "https://example.com:8080/path"

    def test_parse_field_without_colon(self):
        """Lines without colon are skipped."""
        result = parse_sse_line("invalid line")
        assert result is None


class TestSSEEventParsing:
    """Test parse_sse_event function."""

    def test_parse_simple_event(self):
        """Parse event with single data line."""
        lines = [
            "event: message",
            "data: hello world",
        ]
        result = parse_sse_event(lines)
        assert result is not None
        assert result["event"] == "message"
        assert result["data"] == "hello world"

    def test_parse_json_event(self):
        """Parse event with JSON data."""
        lines = [
            'event: delta',
            'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hello"}}',
        ]
        result = parse_sse_event(lines)
        assert result is not None
        assert result["event"] == "delta"
        assert isinstance(result["data"], dict)
        assert result["data"]["type"] == "content_block_delta"

    def test_parse_multiline_json_event(self):
        """Parse event with multiline JSON data (SSE multiline format)."""
        # In SSE, multiline data uses multiple "data:" lines
        lines = [
            'event: message_start',
            'data: {',
            'data: "type": "message_start",',
            'data: "message": {"id": "msg-123"}',
            'data: }',
        ]
        result = parse_sse_event(lines)
        assert result is not None
        assert result["event"] == "message_start"
        # Data lines are concatenated with newlines and parsed as JSON
        assert isinstance(result["data"], dict)
        assert result["data"]["type"] == "message_start"
        assert result["data"]["message"]["id"] == "msg-123"

    def test_parse_missing_event_type(self):
        """Missing event type defaults to 'message' (OpenAI-style SSE)."""
        lines = ['data: hello']
        result = parse_sse_event(lines)
        assert result is not None
        assert result["event"] == "message"
        assert result["data"] == "hello"

    def test_parse_missing_data(self):
        """Missing data returns None."""
        lines = ['event: message']
        result = parse_sse_event(lines)
        assert result is None

    def test_parse_empty_lines_list(self):
        """Empty lines list returns None."""
        result = parse_sse_event([])
        assert result is None

    def test_parse_ignores_comments(self):
        """Comments are ignored during parsing."""
        lines = [
            ":comment line",
            "event: message",
            ":another comment",
            "data: hello",
        ]
        result = parse_sse_event(lines)
        assert result is not None
        assert result["event"] == "message"
        assert result["data"] == "hello"

    def test_parse_invalid_json_fallback(self):
        """Invalid JSON is returned as string."""
        lines = [
            "event: message",
            "data: not valid json {",
        ]
        result = parse_sse_event(lines)
        assert result is not None
        assert result["data"] == "not valid json {"


class TestSSEStreamParser:
    """Test SSEStreamParser stateful parser."""

    def test_parse_single_complete_event(self):
        """Parse a single complete event."""
        parser = SSEStreamParser()
        stream = "event: message\ndata: hello\n\n"
        events = list(parser.feed(stream))
        assert len(events) == 1
        assert events[0]["event"] == "message"
        assert events[0]["data"] == "hello"

    def test_parse_multiple_events(self):
        """Parse multiple events in single feed."""
        parser = SSEStreamParser()
        stream = (
            "event: start\ndata: begin\n\n"
            "event: content\ndata: chunk1\n\n"
            "event: stop\ndata: end\n\n"
        )
        events = list(parser.feed(stream))
        assert len(events) == 3
        assert events[0]["event"] == "start"
        assert events[1]["event"] == "content"
        assert events[2]["event"] == "stop"

    def test_parse_chunked_delivery(self):
        """Handle event delivered in chunks."""
        parser = SSEStreamParser()
        # Deliver line by line
        chunk1 = "event: messa"
        chunk2 = "ge\ndata: hel"
        chunk3 = "lo\n\nevent:"
        chunk4 = " next\n"

        events1 = list(parser.feed(chunk1))
        assert len(events1) == 0  # Incomplete

        events2 = list(parser.feed(chunk2))
        assert len(events2) == 0  # Still incomplete

        events3 = list(parser.feed(chunk3))
        assert len(events3) == 1  # First event complete
        assert events3[0]["event"] == "message"

        events4 = list(parser.feed(chunk4))
        assert len(events4) == 0  # Second event incomplete

    def test_parse_json_chunks(self):
        """Handle JSON delivery split across chunks."""
        parser = SSEStreamParser()
        chunk1 = 'event: delta\ndata: {"type": "text"'
        chunk2 = ', "text": "hello'
        chunk3 = '"}\n\n'

        events = []
        events.extend(parser.feed(chunk1))
        events.extend(parser.feed(chunk2))
        events.extend(parser.feed(chunk3))

        assert len(events) == 1
        assert events[0]["data"]["text"] == "hello"

    def test_parse_with_callback(self):
        """Call callback for each event."""
        received_events = []

        def on_event(event_type, data):
            received_events.append((event_type, data))

        parser = SSEStreamParser(on_event=on_event)
        stream = "event: msg1\ndata: data1\n\nevent: msg2\ndata: data2\n\n"
        list(parser.feed(stream))

        assert len(received_events) == 2
        assert received_events[0] == ("msg1", "data1")
        assert received_events[1] == ("msg2", "data2")

    def test_parse_multiline_data(self):
        """Handle multiline data fields."""
        parser = SSEStreamParser()
        stream = (
            'event: message\n'
            'data: line1\n'
            'data: line2\n'
            'data: line3\n'
            '\n'
        )
        events = list(parser.feed(stream))
        assert len(events) == 1
        assert events[0]["data"] == "line1\nline2\nline3"

    def test_flush_incomplete_event(self):
        """Flush handles incomplete buffered data."""
        parser = SSEStreamParser()
        stream = "event: msg\ndata: hello"
        events = list(parser.feed(stream))
        assert len(events) == 0  # No complete event yet

        # Manually flush
        events = list(parser.flush())
        # Flush adds newline, completing the event
        assert len(events) == 1
        assert events[0]["event"] == "msg"

    def test_parse_empty_stream(self):
        """Parse empty stream returns no events."""
        parser = SSEStreamParser()
        events = list(parser.feed(""))
        assert len(events) == 0

    def test_parse_only_comments(self):
        """Stream with only comments returns no events."""
        parser = SSEStreamParser()
        events = list(parser.feed(":comment1\n:comment2\n\n"))
        assert len(events) == 0

    def test_parse_with_crlf_line_endings(self):
        """Handle CRLF line endings."""
        parser = SSEStreamParser()
        stream = "event: msg\r\ndata: hello\r\n\r\n"
        events = list(parser.feed(stream))
        assert len(events) == 1
        assert events[0]["data"] == "hello"

    def test_parse_large_payload(self):
        """Handle large data payloads."""
        parser = SSEStreamParser()
        large_data = "x" * 10000
        stream = f'event: large\ndata: {{"content": "{large_data}"}}\n\n'
        events = list(parser.feed(stream))
        assert len(events) == 1
        assert len(events[0]["data"]["content"]) == 10000

    def test_parse_special_characters(self):
        """Handle special characters in data."""
        parser = SSEStreamParser()
        special_data = 'émojis 🎉 and \t tabs \n newlines'
        stream = f'event: special\ndata: {json.dumps({"text": special_data})}\n\n'
        events = list(parser.feed(stream))
        assert len(events) == 1
        assert events[0]["data"]["text"] == special_data
