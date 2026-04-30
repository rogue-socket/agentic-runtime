"""Streaming types for token-level LLM responses.

Dataclasses for streaming chunks, complete responses, and validation.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, List
from enum import Enum
import time


class StreamChunkType(Enum):
    """Types of chunks in a streaming response."""
    START = "start"              # Streaming started
    CONTENT = "content"          # Text content chunk
    TOOL_CALL_START = "tool_call_start"  # Tool call starting
    TOOL_CALL_CHUNK = "tool_call_chunk"  # Tool call argument chunk
    TOOL_CALL_END = "tool_call_end"      # Tool call complete
    STOP = "stop"                # Streaming stopped
    ERROR = "error"              # Error occurred


@dataclass(frozen=True)
class StreamChunk:
    """A single chunk from a streaming LLM response.

    Attributes:
        chunk_type: Type of chunk (content, tool_call_chunk, etc.)
        content: String content for CONTENT chunks
        tool_name: Tool name for TOOL_CALL_* chunks
        tool_input_chunk: JSON fragment for TOOL_CALL_CHUNK
        token_count: Estimated tokens in this chunk (for content)
        timestamp_ms: Milliseconds since streaming started
        provider: Which provider generated this (openai, anthropic, gemini)
        model: Model name
        metadata: Extra provider-specific data
    """
    chunk_type: StreamChunkType
    content: Optional[str] = None
    tool_name: Optional[str] = None
    tool_input_chunk: Optional[str] = None
    token_count: Optional[int] = None
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    provider: Optional[str] = None
    model: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate chunk invariants."""
        # CONTENT chunks must have content
        if self.chunk_type == StreamChunkType.CONTENT:
            if not self.content:
                raise ValueError("CONTENT chunks must have non-empty content")
            if self.tool_name or self.tool_input_chunk:
                raise ValueError("CONTENT chunks cannot have tool fields")

        # TOOL_CALL_CHUNK chunks must have tool_name and tool_input_chunk
        elif self.chunk_type == StreamChunkType.TOOL_CALL_CHUNK:
            if not self.tool_name or self.tool_input_chunk is None:
                raise ValueError("TOOL_CALL_CHUNK chunks must have tool_name and tool_input_chunk")
            if self.content:
                raise ValueError("TOOL_CALL_CHUNK chunks cannot have content")

        # TOOL_CALL_START must have tool_name
        elif self.chunk_type == StreamChunkType.TOOL_CALL_START:
            if not self.tool_name:
                raise ValueError("TOOL_CALL_START chunks must have tool_name")

        # TOOL_CALL_END must have tool_name
        elif self.chunk_type == StreamChunkType.TOOL_CALL_END:
            if not self.tool_name:
                raise ValueError("TOOL_CALL_END chunks must have tool_name")

        # ERROR chunks must have content (error message)
        elif self.chunk_type == StreamChunkType.ERROR:
            if not self.content:
                raise ValueError("ERROR chunks must have error message content")

        # token_count must be non-negative if present
        if self.token_count is not None and self.token_count < 0:
            raise ValueError("token_count must be non-negative")

    def is_final(self) -> bool:
        """Whether this chunk marks the end of streaming."""
        return self.chunk_type in (StreamChunkType.STOP, StreamChunkType.ERROR)


@dataclass(frozen=True)
class StreamingLLMResponse:
    """Complete streaming response with all accumulated data.

    Attributes:
        chunks: All chunks received during streaming
        final_content: Complete text content (concatenated from CONTENT chunks)
        final_tool_calls: List of complete tool calls
        total_tokens: Total tokens in response (if available)
        total_input_tokens: Input tokens (if available)
        total_output_tokens: Output tokens (if available)
        duration_ms: Total streaming duration in milliseconds
        provider: Provider that generated this response
        model: Model used
        finish_reason: How streaming ended (stop, tool_calls, error, etc.)
        error: Error message if streaming failed
        metadata: Provider-specific response metadata
    """
    chunks: List[StreamChunk] = field(default_factory=list)
    final_content: str = ""
    final_tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    total_tokens: Optional[int] = None
    total_input_tokens: Optional[int] = None
    total_output_tokens: Optional[int] = None
    duration_ms: int = 0
    provider: Optional[str] = None
    model: Optional[str] = None
    finish_reason: str = "unknown"
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate response invariants."""
        # If error, duration should still be set
        if self.error and not self.chunks:
            # Error with no chunks is okay (early failure)
            pass

        # Token counts should be non-negative
        for tokens in [self.total_tokens, self.total_input_tokens, self.total_output_tokens]:
            if tokens is not None and tokens < 0:
                raise ValueError("Token counts must be non-negative")

        # Duration should be non-negative
        if self.duration_ms < 0:
            raise ValueError("duration_ms must be non-negative")

    @classmethod
    def from_chunks(cls, chunks: List[StreamChunk], duration_ms: int = 0) -> StreamingLLMResponse:
        """Construct a response by accumulating chunks.

        Args:
            chunks: List of chunks to accumulate.
            duration_ms: Total streaming duration.

        Returns:
            A complete StreamingLLMResponse with accumulated data.
        """
        final_content = ""
        final_tool_calls: List[Dict[str, Any]] = []
        total_tokens = 0
        error = None
        finish_reason = "unknown"
        provider = None
        model = None

        current_tool_call: Optional[Dict[str, Any]] = None

        for chunk in chunks:
            # Update provider/model from first chunk that has them
            if provider is None and chunk.provider:
                provider = chunk.provider
            if model is None and chunk.model:
                model = chunk.model

            if chunk.chunk_type == StreamChunkType.CONTENT:
                final_content += chunk.content or ""
                if chunk.token_count:
                    total_tokens += chunk.token_count

            elif chunk.chunk_type == StreamChunkType.TOOL_CALL_START:
                current_tool_call = {"name": chunk.tool_name, "input": ""}

            elif chunk.chunk_type == StreamChunkType.TOOL_CALL_CHUNK:
                if current_tool_call:
                    current_tool_call["input"] += chunk.tool_input_chunk or ""
                if chunk.token_count:
                    total_tokens += chunk.token_count

            elif chunk.chunk_type == StreamChunkType.TOOL_CALL_END:
                if current_tool_call:
                    final_tool_calls.append(current_tool_call)
                    current_tool_call = None

            elif chunk.chunk_type == StreamChunkType.STOP:
                finish_reason = "stop"

            elif chunk.chunk_type == StreamChunkType.ERROR:
                error = chunk.content
                finish_reason = "error"

        return cls(
            chunks=chunks,
            final_content=final_content,
            final_tool_calls=final_tool_calls,
            total_tokens=total_tokens if total_tokens > 0 else None,
            duration_ms=duration_ms,
            provider=provider,
            model=model,
            finish_reason=finish_reason,
            error=error,
        )

    def is_success(self) -> bool:
        """Whether streaming completed successfully."""
        return self.error is None

    def has_content(self) -> bool:
        """Whether response has text content."""
        return len(self.final_content) > 0

    def has_tool_calls(self) -> bool:
        """Whether response has tool calls."""
        return len(self.final_tool_calls) > 0
