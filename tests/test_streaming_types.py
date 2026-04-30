"""Tests for streaming types (StreamChunk, StreamingLLMResponse)."""

from __future__ import annotations
import time
import pytest
from agent_runtime.llm.streaming import (
    StreamChunk,
    StreamChunkType,
    StreamingLLMResponse,
)


class TestStreamChunkValidation:
    """Test StreamChunk validation and invariants."""

    def test_content_chunk_valid(self):
        """Content chunks must have content."""
        chunk = StreamChunk(chunk_type=StreamChunkType.CONTENT, content="Hello")
        assert chunk.content == "Hello"
        assert chunk.is_final() is False

    def test_content_chunk_empty_content_invalid(self):
        """Content chunks cannot have empty content."""
        with pytest.raises(ValueError, match="CONTENT chunks must have non-empty content"):
            StreamChunk(chunk_type=StreamChunkType.CONTENT, content="")

    def test_content_chunk_none_content_invalid(self):
        """Content chunks must have content set."""
        with pytest.raises(ValueError, match="CONTENT chunks must have non-empty content"):
            StreamChunk(chunk_type=StreamChunkType.CONTENT, content=None)

    def test_content_chunk_no_tool_fields(self):
        """Content chunks cannot have tool fields."""
        with pytest.raises(ValueError, match="cannot have tool fields"):
            StreamChunk(
                chunk_type=StreamChunkType.CONTENT,
                content="Hello",
                tool_name="some_tool",
            )

    def test_tool_call_chunk_valid(self):
        """Tool call chunks must have tool_name and tool_input_chunk."""
        chunk = StreamChunk(
            chunk_type=StreamChunkType.TOOL_CALL_CHUNK,
            tool_name="calculator",
            tool_input_chunk='{"x": 5',
        )
        assert chunk.tool_name == "calculator"
        assert chunk.tool_input_chunk == '{"x": 5'

    def test_tool_call_chunk_missing_tool_name(self):
        """Tool call chunks require tool_name."""
        with pytest.raises(ValueError, match="TOOL_CALL_CHUNK chunks must have tool_name"):
            StreamChunk(
                chunk_type=StreamChunkType.TOOL_CALL_CHUNK,
                tool_input_chunk='{"x": 5}',
            )

    def test_tool_call_chunk_missing_input(self):
        """Tool call chunks require tool_input_chunk."""
        with pytest.raises(ValueError, match="TOOL_CALL_CHUNK chunks must have tool_name"):
            StreamChunk(
                chunk_type=StreamChunkType.TOOL_CALL_CHUNK,
                tool_name="calculator",
                tool_input_chunk=None,
            )

    def test_tool_call_chunk_no_content(self):
        """Tool call chunks cannot have content."""
        with pytest.raises(ValueError, match="cannot have content"):
            StreamChunk(
                chunk_type=StreamChunkType.TOOL_CALL_CHUNK,
                tool_name="calculator",
                tool_input_chunk="{}",
                content="Bad",
            )

    def test_tool_call_start_valid(self):
        """Tool call start chunks need tool_name."""
        chunk = StreamChunk(
            chunk_type=StreamChunkType.TOOL_CALL_START,
            tool_name="get_weather",
        )
        assert chunk.tool_name == "get_weather"

    def test_tool_call_start_missing_tool(self):
        """Tool call start requires tool_name."""
        with pytest.raises(ValueError, match="TOOL_CALL_START chunks must have tool_name"):
            StreamChunk(chunk_type=StreamChunkType.TOOL_CALL_START)

    def test_tool_call_end_valid(self):
        """Tool call end chunks need tool_name."""
        chunk = StreamChunk(
            chunk_type=StreamChunkType.TOOL_CALL_END,
            tool_name="get_weather",
        )
        assert chunk.tool_name == "get_weather"

    def test_tool_call_end_missing_tool(self):
        """Tool call end requires tool_name."""
        with pytest.raises(ValueError, match="TOOL_CALL_END chunks must have tool_name"):
            StreamChunk(chunk_type=StreamChunkType.TOOL_CALL_END)

    def test_error_chunk_valid(self):
        """Error chunks must have error message content."""
        chunk = StreamChunk(
            chunk_type=StreamChunkType.ERROR,
            content="Connection timeout",
        )
        assert chunk.content == "Connection timeout"
        assert chunk.is_final() is True

    def test_error_chunk_no_message_invalid(self):
        """Error chunks require error message."""
        with pytest.raises(ValueError, match="ERROR chunks must have error message"):
            StreamChunk(chunk_type=StreamChunkType.ERROR, content=None)

    def test_start_chunk(self):
        """START chunks are valid with minimal fields."""
        chunk = StreamChunk(chunk_type=StreamChunkType.START)
        assert chunk.is_final() is False

    def test_stop_chunk(self):
        """STOP chunks mark end of streaming."""
        chunk = StreamChunk(chunk_type=StreamChunkType.STOP)
        assert chunk.is_final() is True

    def test_negative_token_count_invalid(self):
        """Token count must be non-negative."""
        with pytest.raises(ValueError, match="token_count must be non-negative"):
            StreamChunk(
                chunk_type=StreamChunkType.CONTENT,
                content="Hello",
                token_count=-1,
            )

    def test_zero_token_count_valid(self):
        """Zero token count is valid."""
        chunk = StreamChunk(
            chunk_type=StreamChunkType.CONTENT,
            content="Hello",
            token_count=0,
        )
        assert chunk.token_count == 0

    def test_chunk_with_metadata(self):
        """Chunks can carry provider-specific metadata."""
        chunk = StreamChunk(
            chunk_type=StreamChunkType.CONTENT,
            content="Hello",
            provider="openai",
            model="gpt-4o",
            metadata={"finish_reason": "length"},
        )
        assert chunk.provider == "openai"
        assert chunk.model == "gpt-4o"
        assert chunk.metadata["finish_reason"] == "length"

    def test_chunk_frozen(self):
        """StreamChunk is frozen (immutable)."""
        chunk = StreamChunk(chunk_type=StreamChunkType.CONTENT, content="Hello")
        with pytest.raises(AttributeError):
            chunk.content = "World"  # type: ignore

    def test_chunk_timestamp_auto_set(self):
        """Chunk timestamp is auto-set if not provided."""
        before = int(time.time() * 1000)
        chunk = StreamChunk(chunk_type=StreamChunkType.CONTENT, content="Hello")
        after = int(time.time() * 1000)
        assert before <= chunk.timestamp_ms <= after


class TestStreamingLLMResponseAccumulation:
    """Test StreamingLLMResponse.from_chunks accumulation logic."""

    def test_from_chunks_content_only(self):
        """Accumulate content chunks into final_content."""
        chunks = [
            StreamChunk(chunk_type=StreamChunkType.START),
            StreamChunk(chunk_type=StreamChunkType.CONTENT, content="Hello "),
            StreamChunk(chunk_type=StreamChunkType.CONTENT, content="World"),
            StreamChunk(chunk_type=StreamChunkType.STOP),
        ]
        response = StreamingLLMResponse.from_chunks(chunks, duration_ms=100)
        assert response.final_content == "Hello World"
        assert response.finish_reason == "stop"
        assert response.is_success() is True
        assert response.error is None

    def test_from_chunks_tool_calls(self):
        """Accumulate tool call chunks into final_tool_calls."""
        chunks = [
            StreamChunk(chunk_type=StreamChunkType.START),
            StreamChunk(chunk_type=StreamChunkType.TOOL_CALL_START, tool_name="calculator"),
            StreamChunk(
                chunk_type=StreamChunkType.TOOL_CALL_CHUNK,
                tool_name="calculator",
                tool_input_chunk='{"operation": "',
            ),
            StreamChunk(
                chunk_type=StreamChunkType.TOOL_CALL_CHUNK,
                tool_name="calculator",
                tool_input_chunk='add", "x": 5',
            ),
            StreamChunk(
                chunk_type=StreamChunkType.TOOL_CALL_CHUNK,
                tool_name="calculator",
                tool_input_chunk=', "y": 3}',
            ),
            StreamChunk(chunk_type=StreamChunkType.TOOL_CALL_END, tool_name="calculator"),
            StreamChunk(chunk_type=StreamChunkType.STOP),
        ]
        response = StreamingLLMResponse.from_chunks(chunks)
        assert len(response.final_tool_calls) == 1
        assert response.final_tool_calls[0]["name"] == "calculator"
        assert response.final_tool_calls[0]["input"] == '{"operation": "add", "x": 5, "y": 3}'

    def test_from_chunks_mixed_content_and_tools(self):
        """Handle mixed content and tool calls."""
        chunks = [
            StreamChunk(chunk_type=StreamChunkType.CONTENT, content="Let me calculate. "),
            StreamChunk(chunk_type=StreamChunkType.TOOL_CALL_START, tool_name="math"),
            StreamChunk(
                chunk_type=StreamChunkType.TOOL_CALL_CHUNK,
                tool_name="math",
                tool_input_chunk='{"expr": "2+2"}',
            ),
            StreamChunk(chunk_type=StreamChunkType.TOOL_CALL_END, tool_name="math"),
        ]
        response = StreamingLLMResponse.from_chunks(chunks)
        assert response.final_content == "Let me calculate. "
        assert len(response.final_tool_calls) == 1
        assert response.final_tool_calls[0]["name"] == "math"

    def test_from_chunks_token_counting(self):
        """Accumulate token counts across chunks."""
        chunks = [
            StreamChunk(chunk_type=StreamChunkType.CONTENT, content="Hello", token_count=1),
            StreamChunk(chunk_type=StreamChunkType.CONTENT, content=" World", token_count=1),
            StreamChunk(
                chunk_type=StreamChunkType.TOOL_CALL_CHUNK,
                tool_name="test",
                tool_input_chunk="{}",
                token_count=2,
            ),
        ]
        response = StreamingLLMResponse.from_chunks(chunks)
        assert response.total_tokens == 4

    def test_from_chunks_error(self):
        """Handle error chunks."""
        chunks = [
            StreamChunk(chunk_type=StreamChunkType.START),
            StreamChunk(chunk_type=StreamChunkType.CONTENT, content="Partial "),
            StreamChunk(chunk_type=StreamChunkType.ERROR, content="Connection lost"),
        ]
        response = StreamingLLMResponse.from_chunks(chunks)
        assert response.final_content == "Partial "
        assert response.error == "Connection lost"
        assert response.finish_reason == "error"
        assert response.is_success() is False

    def test_from_chunks_provider_and_model(self):
        """Extract provider and model from first chunk that has them."""
        chunks = [
            StreamChunk(chunk_type=StreamChunkType.CONTENT, content="Hello"),
            StreamChunk(
                chunk_type=StreamChunkType.CONTENT,
                content=" World",
                provider="openai",
                model="gpt-4o",
            ),
        ]
        response = StreamingLLMResponse.from_chunks(chunks)
        assert response.provider == "openai"
        assert response.model == "gpt-4o"

    def test_from_chunks_empty(self):
        """Handle empty chunks list."""
        response = StreamingLLMResponse.from_chunks([])
        assert response.final_content == ""
        assert response.final_tool_calls == []
        assert response.total_tokens is None
        assert response.is_success() is True

    def test_response_validation_negative_tokens_invalid(self):
        """Negative token counts are invalid."""
        with pytest.raises(ValueError, match="Token counts must be non-negative"):
            StreamingLLMResponse(total_tokens=-1)

    def test_response_validation_negative_duration_invalid(self):
        """Negative duration is invalid."""
        with pytest.raises(ValueError, match="duration_ms must be non-negative"):
            StreamingLLMResponse(duration_ms=-1)

    def test_response_has_content(self):
        """Test has_content() method."""
        resp_with_content = StreamingLLMResponse(final_content="Hello")
        resp_empty = StreamingLLMResponse(final_content="")
        assert resp_with_content.has_content() is True
        assert resp_empty.has_content() is False

    def test_response_has_tool_calls(self):
        """Test has_tool_calls() method."""
        resp_with_tools = StreamingLLMResponse(
            final_tool_calls=[{"name": "test", "input": "{}"}]
        )
        resp_no_tools = StreamingLLMResponse(final_tool_calls=[])
        assert resp_with_tools.has_tool_calls() is True
        assert resp_no_tools.has_tool_calls() is False

    def test_response_frozen(self):
        """StreamingLLMResponse is frozen (immutable)."""
        response = StreamingLLMResponse(final_content="Hello")
        with pytest.raises(AttributeError):
            response.final_content = "World"  # type: ignore

    def test_response_multiple_tool_calls(self):
        """Handle multiple tool calls in a single response."""
        chunks = [
            # First tool
            StreamChunk(chunk_type=StreamChunkType.TOOL_CALL_START, tool_name="tool1"),
            StreamChunk(
                chunk_type=StreamChunkType.TOOL_CALL_CHUNK,
                tool_name="tool1",
                tool_input_chunk='{"x": 1}',
            ),
            StreamChunk(chunk_type=StreamChunkType.TOOL_CALL_END, tool_name="tool1"),
            # Second tool
            StreamChunk(chunk_type=StreamChunkType.TOOL_CALL_START, tool_name="tool2"),
            StreamChunk(
                chunk_type=StreamChunkType.TOOL_CALL_CHUNK,
                tool_name="tool2",
                tool_input_chunk='{"y": 2}',
            ),
            StreamChunk(chunk_type=StreamChunkType.TOOL_CALL_END, tool_name="tool2"),
        ]
        response = StreamingLLMResponse.from_chunks(chunks)
        assert len(response.final_tool_calls) == 2
        assert response.final_tool_calls[0]["name"] == "tool1"
        assert response.final_tool_calls[1]["name"] == "tool2"

    def test_chunk_type_enum(self):
        """Test all StreamChunkType enum values."""
        assert StreamChunkType.START.value == "start"
        assert StreamChunkType.CONTENT.value == "content"
        assert StreamChunkType.TOOL_CALL_START.value == "tool_call_start"
        assert StreamChunkType.TOOL_CALL_CHUNK.value == "tool_call_chunk"
        assert StreamChunkType.TOOL_CALL_END.value == "tool_call_end"
        assert StreamChunkType.STOP.value == "stop"
        assert StreamChunkType.ERROR.value == "error"
