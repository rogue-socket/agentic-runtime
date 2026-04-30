"""Tests for LLM adapter streaming methods."""

from __future__ import annotations
import json
import pytest
from unittest.mock import Mock, patch, MagicMock
from io import BytesIO

from agent_runtime.llm.adapters import OpenAIAdapter, AnthropicAdapter, GeminiAdapter
from agent_runtime.llm.streaming import StreamChunk, StreamChunkType, StreamingLLMResponse


class MockStreamResponse:
    """Mock response object that properly supports iteration."""

    def __init__(self, lines):
        self.lines = lines

    def __iter__(self):
        return iter(self.lines)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class TestOpenAIAdapterStreaming:
    """Test OpenAI streaming implementation."""

    def test_openai_stream_parses_content_chunks(self):
        """OpenAI stream() parses content chunks."""
        adapter = OpenAIAdapter()

        with patch("agent_runtime.llm.adapters._urlopen_with_retry") as mock_urlopen:
            mock_response = MockStreamResponse([
                b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n',
                b'data: {"choices":[{"delta":{"content":" "}}]}\n\n',
                b'data: {"choices":[{"delta":{"content":"World"}}]}\n\n',
                b'data: [DONE]\n\n',
            ])
            mock_urlopen.return_value = mock_response

            chunks = list(adapter.stream(
                api_key="sk-test-123",
                model="gpt-4o",
                prompt="Hello",
                system=None,
                params={},
                base_url=None,
                tools=None,
            ))

            content_chunks = [c for c in chunks if c.chunk_type == StreamChunkType.CONTENT]
            assert len(content_chunks) >= 1
            assert any("Hello" in (c.content or "") for c in content_chunks)

    def test_openai_stream_handles_tool_calls(self):
        """OpenAI stream() parses tool call chunks."""
        adapter = OpenAIAdapter()

        with patch("agent_runtime.llm.adapters._urlopen_with_retry") as mock_urlopen:
            mock_response = MockStreamResponse([
                b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"calculator"}}]}}]}\n\n',
                b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{"}}]}}]}\n\n',
                b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"x\": 5}"}}]}}]}\n\n',
                b'data: [DONE]\n\n',
            ])
            mock_urlopen.return_value = mock_response

            chunks = list(adapter.stream(
                api_key="sk-test-123",
                model="gpt-4o",
                prompt="Calculate 1+1",
                system=None,
                params={},
                base_url=None,
                tools=[{
                    "name": "calculator",
                    "description": "Calculate",
                    "parameters": {"type": "object"},
                }],
            ))

            tool_calls = [c for c in chunks if c.chunk_type in {
                StreamChunkType.TOOL_CALL_START,
                StreamChunkType.TOOL_CALL_CHUNK,
                StreamChunkType.TOOL_CALL_END,
            }]
            assert len(tool_calls) > 0


class TestAnthropicAdapterStreaming:
    """Test Anthropic streaming implementation."""

    def test_anthropic_stream_parses_content_blocks(self):
        """Anthropic stream() parses content_block_delta events."""
        adapter = AnthropicAdapter()

        with patch("agent_runtime.llm.adapters._urlopen_with_retry") as mock_urlopen:
            mock_response = MockStreamResponse([
                b'event: content_block_start\ndata: {"type": "content_block_start"}\n\n',
                b'event: content_block_delta\ndata: {"delta": {"type": "text_delta", "text": "Hello"}}\n\n',
                b'event: content_block_delta\ndata: {"delta": {"type": "text_delta", "text": " World"}}\n\n',
                b'event: message_stop\ndata: {"type": "message_stop"}\n\n',
            ])
            mock_urlopen.return_value = mock_response

            chunks = list(adapter.stream(
                api_key="sk-ant-test-123",
                model="claude-3-5-sonnet",
                prompt="Hello",
                system=None,
                params={},
                base_url=None,
                tools=None,
            ))

            content_chunks = [c for c in chunks if c.chunk_type == StreamChunkType.CONTENT]
            assert len(content_chunks) >= 2

    def test_anthropic_stream_handles_tool_use(self):
        """Anthropic stream() parses tool_use blocks."""
        adapter = AnthropicAdapter()

        with patch("agent_runtime.llm.adapters._urlopen_with_retry") as mock_urlopen:
            mock_response = MockStreamResponse([
                b'event: content_block_start\ndata: {"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": "tool_1", "name": "calculator", "input": {}}}\n\n',
                b'event: content_block_delta\ndata: {"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": "{\\"x\\": 5"}}\n\n',
                b'event: content_block_stop\ndata: {"type": "content_block_stop"}\n\n',
            ])
            mock_urlopen.return_value = mock_response

            chunks = list(adapter.stream(
                api_key="sk-ant-test-123",
                model="claude-3-5-sonnet",
                prompt="Calculate",
                system=None,
                params={},
                base_url=None,
                tools=[{
                    "name": "calculator",
                    "description": "Calculate",
                    "parameters": {"type": "object"},
                }],
            ))

            tool_chunks = [c for c in chunks if c.chunk_type in {
                StreamChunkType.TOOL_CALL_START,
                StreamChunkType.TOOL_CALL_CHUNK,
                StreamChunkType.TOOL_CALL_END,
            }]
            assert len(tool_chunks) > 0


class TestStreamingResponseAccumulation:
    """Test accumulated streaming responses."""

    def test_accumulate_openai_streaming_response(self):
        """Accumulate OpenAI streaming chunks into response."""
        chunks = [
            StreamChunk(chunk_type=StreamChunkType.START, provider="openai", model="gpt-4o"),
            StreamChunk(chunk_type=StreamChunkType.CONTENT, content="Hello ", token_count=1),
            StreamChunk(chunk_type=StreamChunkType.CONTENT, content="World", token_count=1),
            StreamChunk(chunk_type=StreamChunkType.STOP),
        ]

        response = StreamingLLMResponse.from_chunks(chunks, duration_ms=250)
        assert response.final_content == "Hello World"
        assert response.total_tokens == 2
        assert response.is_success()
        assert response.provider == "openai"
        assert response.model == "gpt-4o"

    def test_accumulate_anthropic_tool_response(self):
        """Accumulate Anthropic tool call chunks."""
        chunks = [
            StreamChunk(chunk_type=StreamChunkType.TOOL_CALL_START, tool_name="get_weather", provider="anthropic"),
            StreamChunk(
                chunk_type=StreamChunkType.TOOL_CALL_CHUNK,
                tool_name="get_weather",
                tool_input_chunk='{"location": "',
            ),
            StreamChunk(
                chunk_type=StreamChunkType.TOOL_CALL_CHUNK,
                tool_name="get_weather",
                tool_input_chunk='San Francisco"}',
            ),
            StreamChunk(chunk_type=StreamChunkType.TOOL_CALL_END, tool_name="get_weather"),
            StreamChunk(chunk_type=StreamChunkType.STOP),
        ]

        response = StreamingLLMResponse.from_chunks(chunks)
        assert len(response.final_tool_calls) == 1
        assert response.final_tool_calls[0]["name"] == "get_weather"
        assert "San Francisco" in response.final_tool_calls[0]["input"]

    def test_streaming_response_with_mixed_content_and_tools(self):
        """Handle response with both content and tool calls."""
        chunks = [
            StreamChunk(chunk_type=StreamChunkType.CONTENT, content="I'll help you check the weather. "),
            StreamChunk(chunk_type=StreamChunkType.TOOL_CALL_START, tool_name="get_weather"),
            StreamChunk(
                chunk_type=StreamChunkType.TOOL_CALL_CHUNK,
                tool_name="get_weather",
                tool_input_chunk='{"city": "NYC"}',
            ),
            StreamChunk(chunk_type=StreamChunkType.TOOL_CALL_END, tool_name="get_weather"),
            StreamChunk(chunk_type=StreamChunkType.STOP),
        ]

        response = StreamingLLMResponse.from_chunks(chunks)
        assert "weather" in response.final_content
        assert len(response.final_tool_calls) == 1


class TestStreamingEdgeCases:
    """Test edge cases and error scenarios."""

    def test_stream_empty_response(self):
        """Handle empty streaming response."""
        response = StreamingLLMResponse.from_chunks([])
        assert response.final_content == ""
        assert response.final_tool_calls == []
        assert response.is_success()

    def test_stream_network_error(self):
        """Handle network error during streaming."""
        chunks = [
            StreamChunk(chunk_type=StreamChunkType.START),
            StreamChunk(chunk_type=StreamChunkType.CONTENT, content="Partial"),
            StreamChunk(
                chunk_type=StreamChunkType.ERROR,
                content="Connection reset by peer",
            ),
        ]

        response = StreamingLLMResponse.from_chunks(chunks)
        assert response.final_content == "Partial"
        assert not response.is_success()
        assert "Connection reset" in response.error

    def test_stream_timeout(self):
        """Handle streaming timeout."""
        chunks = [
            StreamChunk(chunk_type=StreamChunkType.START),
            StreamChunk(chunk_type=StreamChunkType.CONTENT, content="Started"),
            StreamChunk(
                chunk_type=StreamChunkType.ERROR,
                content="Request timeout after 30s",
            ),
        ]

        response = StreamingLLMResponse.from_chunks(chunks)
        assert "timeout" in response.error.lower()
        assert response.finish_reason == "error"

    def test_stream_very_large_chunk(self):
        """Handle very large individual chunks."""
        large_content = "x" * 100000
        chunks = [
            StreamChunk(chunk_type=StreamChunkType.CONTENT, content=large_content, token_count=50000),
            StreamChunk(chunk_type=StreamChunkType.STOP),
        ]

        response = StreamingLLMResponse.from_chunks(chunks)
        assert len(response.final_content) == 100000
        assert response.total_tokens == 50000

    def test_stream_rapid_fire_chunks(self):
        """Handle rapid successive small chunks."""
        chunks = [StreamChunk(chunk_type=StreamChunkType.CONTENT, content="x") for _ in range(1000)]
        chunks.append(StreamChunk(chunk_type=StreamChunkType.STOP))

        response = StreamingLLMResponse.from_chunks(chunks)
        assert len(response.final_content) == 1000
        assert len(response.chunks) == 1001

    def test_stream_unicode_content(self):
        """Handle unicode and emoji in streaming content."""
        chunks = [
            StreamChunk(chunk_type=StreamChunkType.CONTENT, content="Hello "),
            StreamChunk(chunk_type=StreamChunkType.CONTENT, content="世界 "),
            StreamChunk(chunk_type=StreamChunkType.CONTENT, content="🌍"),
            StreamChunk(chunk_type=StreamChunkType.STOP),
        ]

        response = StreamingLLMResponse.from_chunks(chunks)
        assert "世界" in response.final_content
        assert "🌍" in response.final_content
