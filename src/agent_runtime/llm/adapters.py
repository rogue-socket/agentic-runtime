from __future__ import annotations

"""LLM adapter implementations (HTTP clients per provider)."""

from typing import Any, Dict, List, Optional, Protocol, Iterator
import json
import time
import urllib.error
import urllib.request

from .types import LLMResponse, ToolCallRequest
from .streaming import StreamChunk, StreamChunkType, StreamingLLMResponse
from .sse import SSEStreamParser

# Default HTTP timeout in seconds.
DEFAULT_TIMEOUT: int = 60

# Default retry config for transient HTTP errors (429, 500, 502, 503, 504).
DEFAULT_MAX_RETRIES: int = 2
DEFAULT_INITIAL_DELAY: float = 1.0

_RETRYABLE_CODES = frozenset({429, 500, 502, 503, 504})


class MockAdapter:
    """Mock LLM adapter for offline demos and tests.
    
    Returns a deterministic response containing a summary of the input,
    simulating a successful reasoning turn without making network calls.
    """

    provider_name = "mock"

    def call(
        self,
        *,
        api_key: str,
        model: str,
        prompt: str,
        system: Optional[str],
        params: Dict[str, Any],
        base_url: Optional[str],
        history: Optional[List[Dict[str, Any]]] = None,
        context: Optional[Dict[str, Any]] = None,
        timeout: int = DEFAULT_TIMEOUT,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        # Simulate slight delay
        """Function implementation."""
        time.sleep(0.5)
        
        tool_calls = []
        text = f"[MOCK] Processing: \"{prompt[:40]}...\""
        
        # Simple ReAct simulation:
        # 1. If we have tools and no tool results in history yet, return a tool call.
        # 2. If we have tool results in history, return a final answer.
        
        has_results = False
        if history:
            for msg in history:
                role = msg.get("role")
                content = msg.get("content", "")
                if role in {"tool_results", "tool"}:
                    has_results = True
                    break
                if role == "user" and isinstance(content, str) and "Tool observation:" in content:
                    has_results = True
                    break
        
        if tools and not has_results:
            tool = tools[0]
            tool_calls = [
                ToolCallRequest(
                    id=f"call_{int(time.monotonic())}",
                    tool_name=tool["name"],
                    tool_input={"query": "mock search", "input": "mock data"},
                )
            ]
            text = f"I will use the {tool['name']} tool to help answer the user's request."
        elif has_results:
            text = f"Based on the tool results, I can confirm that the operation was successful. [MOCK FINISHED]"
            # Add final answer markers for text parsers just in case
            text += "\n```final_answer\n{\"result\": \"success\"}\n```"
        else:
            text = f"Hello! I am the mock adapter. I received your prompt: \"{prompt}\". How can I help?"
            text += "\n```final_answer\n{\"result\": \"success\"}\n```"

        return LLMResponse(
            text=text,
            provider=self.provider_name,
            model=model,
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            raw={"status": "mock_success"},
            tool_calls=tool_calls,
        )



def _urlopen_with_retry(
    req: urllib.request.Request,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    initial_delay: float = DEFAULT_INITIAL_DELAY,
) -> Any:
    """Execute an HTTP request with timeout and exponential-backoff retry."""
    last_exc: Exception | None = None
    for attempt in range(1 + max_retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in _RETRYABLE_CODES and attempt < max_retries:
                last_exc = exc
                time.sleep(initial_delay * (2 ** attempt))
                continue
            raise
        except urllib.error.URLError:
            raise
    raise AssertionError("unreachable: retry loop always returns or raises")


# ---------------------------------------------------------------------------
# Provider-agnostic history format
# ---------------------------------------------------------------------------
# The strategy layer emits generic history entries that each adapter translates
# into its own wire format.  Two sentinel role values carry native tool call
# information:
#
#   "tool_results"
#       A batch of tool execution results to send back after the model requested
#       native tool calls.  Contains a "_native_results" list, each entry:
#           {"id": str, "name": str, "content": str (JSON)}
#
#   assistant entry with "_native_tool_calls" key
#       The prior assistant turn that requested tool calls.  Contains:
#           "_native_tool_calls": [{"id": str, "name": str, "input": dict}, ...]
#
# Plain {"role": "assistant"/"user", "content": str} entries are passed
# through as-is (text-based fallback path).
# ---------------------------------------------------------------------------


def _build_openai_messages(
    system: Optional[str],
    history: Optional[List[Dict[str, Any]]],
    prompt: str,
) -> List[Dict[str, Any]]:
    """Build OpenAI Chat Completions messages from system, history, and prompt."""
    messages: List[Dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    for msg in (history or []):
        role = msg.get("role", "user")
        if role == "tool_results":
            # One `tool` message per result, matched by tool_call_id.
            for r in msg.get("_native_results", []):
                messages.append({
                    "role": "tool",
                    "tool_call_id": r["id"],
                    "content": r["content"],
                })
        elif role == "assistant" and "_native_tool_calls" in msg:
            # Must replay the original tool_calls array so the model can
            # correlate result messages to prior requests.
            messages.append({
                "role": "assistant",
                "content": msg.get("content") or None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["input"]),
                        },
                    }
                    for tc in msg["_native_tool_calls"]
                ],
            })
        else:
            messages.append({"role": role, "content": msg.get("content", "")})
    messages.append({"role": "user", "content": prompt})
    return messages


def _build_anthropic_messages(
    history: Optional[List[Dict[str, Any]]],
    prompt: str,
) -> List[Dict[str, Any]]:
    """Build Anthropic Messages API messages from history and prompt.

    System prompt is passed separately as a top-level body field.
    """
    messages: List[Dict[str, Any]] = []
    for msg in (history or []):
        role = msg.get("role", "user")
        if role == "tool_results":
            # Tool results go in a user message with tool_result content blocks.
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": r["id"],
                        "content": r["content"],
                    }
                    for r in msg.get("_native_results", [])
                ],
            })
        elif role == "assistant" and "_native_tool_calls" in msg:
            # Mix text block(s) and tool_use blocks in the assistant content array.
            content_blocks: List[Dict[str, Any]] = []
            if msg.get("content"):
                content_blocks.append({"type": "text", "text": msg["content"]})
            for tc in msg["_native_tool_calls"]:
                content_blocks.append({
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": tc["input"],
                })
            messages.append({"role": "assistant", "content": content_blocks})
        else:
            messages.append({"role": role, "content": msg.get("content", "")})
    messages.append({"role": "user", "content": prompt})
    return messages


def _build_gemini_contents(
    history: Optional[List[Dict[str, Any]]],
    prompt: str,
) -> List[Dict[str, Any]]:
    """Build Gemini generateContent ``contents`` list from history and prompt."""
    contents: List[Dict[str, Any]] = []
    for msg in (history or []):
        role = msg.get("role", "user")
        if role == "tool_results":
            # functionResponse parts in a user-role content block.
            parts = []
            for r in msg.get("_native_results", []):
                # Gemini expects the response value as a structured dict.
                try:
                    result_value = json.loads(r["content"])
                except (json.JSONDecodeError, TypeError):
                    result_value = r["content"]
                parts.append({
                    "functionResponse": {
                        "name": r["name"],
                        "response": {"result": result_value},
                    }
                })
            contents.append({"role": "user", "parts": parts})
        elif role == "assistant" and "_native_tool_calls" in msg:
            # Gemini uses "model" role; functionCall parts for tool requests.
            parts: List[Dict[str, Any]] = []
            if msg.get("content"):
                parts.append({"text": msg["content"]})
            for tc in msg["_native_tool_calls"]:
                parts.append({
                    "functionCall": {
                        "name": tc["name"],
                        "args": tc["input"],
                    }
                })
            contents.append({"role": "model", "parts": parts})
        else:
            gemini_role = "model" if role == "assistant" else "user"
            contents.append({
                "role": gemini_role,
                "parts": [{"text": msg.get("content", "")}],
            })
    contents.append({"role": "user", "parts": [{"text": prompt}]})
    return contents


# ---------------------------------------------------------------------------
# Adapter Protocol
# ---------------------------------------------------------------------------
# [Pain Point Solved] #5 Framework Lock-in / Dependency Hell: Provider-agnostic
#   Protocol — any backend implements call(). All adapters use stdlib urllib, so
#   zero SDK dependencies. Swapping OpenAI for Gemini is a config change, not a refactor.
# ---------------------------------------------------------------------------
class LLMAdapter(Protocol):
    """Protocol for provider-specific adapters."""

    provider_name: str

    def call(
        self,
        *,
        api_key: str,
        model: str,
        prompt: str,
        system: Optional[str],
        params: Dict[str, Any],
        base_url: Optional[str],
        history: Optional[List[Dict[str, Any]]] = None,
        context: Optional[Dict[str, Any]] = None,
        timeout: int = DEFAULT_TIMEOUT,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        """Execute an LLM request and return a normalized response.

        Args:
            tools: Provider-agnostic tool schema list for native function calling.
                   Each entry: ``{"name": str, "description": str, "parameters": JSON Schema}``.
                   Pass ``None`` to disable native function calling.
        """
        ...


class OpenAIAdapter:
    """Minimal OpenAI-compatible adapter using the Chat Completions API.

    Native function calling is activated when ``tools`` is non-empty:
      - Adds ``"tools"`` array and ``"tool_choice": "auto"`` to the payload.
      - Parses ``tool_calls`` from the response, populating
        ``LLMResponse.tool_calls`` with ``ToolCallRequest`` objects.
      - Translates ``_native_tool_calls`` / ``tool_results`` history entries
        into the correct OpenAI wire format for multi-turn tool conversations.

    TODO(roadmap): Support streaming (stream=True) for token-level feedback.
    """

    provider_name = "openai"

    def call(
        self,
        *,
        api_key: str,
        model: str,
        prompt: str,
        system: Optional[str],
        params: Dict[str, Any],
        base_url: Optional[str],
        history: Optional[List[Dict[str, Any]]] = None,
        context: Optional[Dict[str, Any]] = None,
        timeout: int = DEFAULT_TIMEOUT,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        """Function implementation."""
        if not api_key:
            raise ValueError("Missing OpenAI API key.")

        base = base_url or "https://api.openai.com/v1"
        url = base.rstrip("/") + "/chat/completions"

        messages = _build_openai_messages(system, history, prompt)
        payload: Dict[str, Any] = {"model": model, "messages": messages}
        payload.update({k: v for k, v in params.items() if v is not None})

        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["parameters"],
                    },
                }
                for tool in tools
            ]
            payload["tool_choice"] = "auto"

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            raw = _urlopen_with_retry(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8") if exc.fp else ""
            raise RuntimeError(f"OpenAI API error ({exc.code}): {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"OpenAI API request failed: {exc}") from exc

        choices = raw.get("choices") or []
        if not choices:
            raise RuntimeError("OpenAI API returned no choices.")
        message = choices[0].get("message") or {}
        content = message.get("content") or ""

        # Parse native tool calls from the response message.
        native_tool_calls: List[ToolCallRequest] = []
        for tc in (message.get("tool_calls") or []):
            try:
                tool_input = json.loads(tc["function"]["arguments"])
            except (json.JSONDecodeError, KeyError):
                tool_input = {}
            native_tool_calls.append(ToolCallRequest(
                id=tc["id"],
                tool_name=tc["function"]["name"],
                tool_input=tool_input,
            ))

        if not content and not native_tool_calls:
            raise RuntimeError("OpenAI API returned an empty response message.")

        return LLMResponse(
            text=content,
            provider=self.provider_name,
            model=model,
            usage=raw.get("usage"),
            raw=raw,
            tool_calls=native_tool_calls,
        )

    def stream(
        self,
        *,
        api_key: str,
        model: str,
        prompt: str,
        system: Optional[str],
        params: Dict[str, Any],
        base_url: Optional[str],
        history: Optional[List[Dict[str, Any]]] = None,
        context: Optional[Dict[str, Any]] = None,
        timeout: int = DEFAULT_TIMEOUT,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Iterator[StreamChunk]:
        """Stream an LLM response, yielding chunks.

        Yields:
            StreamChunk objects as they arrive from the API.
        """
        if not api_key:
            raise ValueError("Missing OpenAI API key.")

        base = base_url or "https://api.openai.com/v1"
        url = base.rstrip("/") + "/chat/completions"

        messages = _build_openai_messages(system, history, prompt)
        payload: Dict[str, Any] = {"model": model, "messages": messages, "stream": True}
        payload.update({k: v for k, v in params.items() if v is not None and k != "stream"})

        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["parameters"],
                    },
                }
                for tool in tools
            ]
            payload["tool_choice"] = "auto"

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with _urlopen_with_retry(req, timeout=timeout) as response:
                parser = SSEStreamParser()
                for line in response:
                    # Parse SSE events
                    for event in parser.feed(line.decode("utf-8")):
                        yield self._openai_parse_event(event, model)
                # Flush remaining events
                for event in parser.flush():
                    yield self._openai_parse_event(event, model)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8") if exc.fp else ""
            try:
                error_data = json.loads(body)
                error_msg = error_data.get("error", {}).get("message", body)
            except json.JSONDecodeError:
                error_msg = body
            yield StreamChunk(
                chunk_type=StreamChunkType.ERROR,
                content=f"OpenAI API error: {error_msg}",
                provider=self.provider_name,
                model=model,
            )

    def _openai_parse_event(self, event: Dict[str, Any], model: str) -> StreamChunk:
        """Parse an OpenAI SSE event into a StreamChunk."""
        event_type = event.get("event", "")
        data = event.get("data", {})

        if event_type == "error":
            return StreamChunk(
                chunk_type=StreamChunkType.ERROR,
                content=str(data),
                provider=self.provider_name,
                model=model,
            )

        # Handle the 'data: [DONE]' message
        if isinstance(data, str) and data == "[DONE]":
            return StreamChunk(
                chunk_type=StreamChunkType.STOP,
                provider=self.provider_name,
                model=model,
            )

        if not isinstance(data, dict):
            return StreamChunk(
                chunk_type=StreamChunkType.ERROR,
                content=f"Unexpected event data: {data}",
                provider=self.provider_name,
                model=model,
            )

        # Process choices
        choices = data.get("choices", [])
        if not choices:
            return StreamChunk(chunk_type=StreamChunkType.START, provider=self.provider_name, model=model)

        choice = choices[0]
        delta = choice.get("delta", {})

        # Check for content
        if "content" in delta and delta["content"]:
            return StreamChunk(
                chunk_type=StreamChunkType.CONTENT,
                content=delta["content"],
                provider=self.provider_name,
                model=model,
            )

        # Check for tool calls
        if "tool_calls" in delta:
            tool_calls = delta["tool_calls"]
            if tool_calls:
                tc = tool_calls[0]
                if "function" in tc and "name" in tc["function"]:
                    return StreamChunk(
                        chunk_type=StreamChunkType.TOOL_CALL_START,
                        tool_name=tc["function"]["name"],
                        provider=self.provider_name,
                        model=model,
                    )
                if "function" in tc and "arguments" in tc["function"]:
                    return StreamChunk(
                        chunk_type=StreamChunkType.TOOL_CALL_CHUNK,
                        tool_name=tc.get("function", {}).get("name", "unknown"),
                        tool_input_chunk=tc["function"]["arguments"],
                        provider=self.provider_name,
                        model=model,
                    )

        # Default to start marker for empty deltas
        return StreamChunk(chunk_type=StreamChunkType.START, provider=self.provider_name, model=model)


class AnthropicAdapter:
    """Adapter for the Anthropic Messages API.

    Native tool use is activated when ``tools`` is non-empty:
      - Adds ``"tools"`` array (using ``input_schema`` field) to the request body.
      - Parses ``tool_use`` content blocks from the response, populating
        ``LLMResponse.tool_calls`` with ``ToolCallRequest`` objects.
      - Translates ``_native_tool_calls`` / ``tool_results`` history entries
        into Anthropic's multi-content-block format for multi-turn conversations.

    TODO(roadmap): Add streaming support for token-level feedback.
    """

    provider_name = "anthropic"

    def call(
        self,
        *,
        api_key: str,
        model: str,
        prompt: str,
        system: Optional[str],
        params: Dict[str, Any],
        base_url: Optional[str],
        history: Optional[List[Dict[str, Any]]] = None,
        context: Optional[Dict[str, Any]] = None,
        timeout: int = DEFAULT_TIMEOUT,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        """Function implementation."""
        if not api_key:
            raise ValueError("Missing Anthropic API key.")

        base = base_url or "https://api.anthropic.com"
        url = base.rstrip("/") + "/v1/messages"

        messages = _build_anthropic_messages(history, prompt)
        body: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": params.get("max_tokens", 4096),
        }
        if system:
            body["system"] = system
        body.update({k: v for k, v in params.items() if v is not None})

        if tools:
            body["tools"] = [
                {
                    "name": tool["name"],
                    "description": tool["description"],
                    # Anthropic uses "input_schema" instead of "parameters".
                    "input_schema": tool["parameters"],
                }
                for tool in tools
            ]

        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            raw = _urlopen_with_retry(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8") if exc.fp else ""
            raise RuntimeError(f"Anthropic API error ({exc.code}): {body_text}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Anthropic API request failed: {exc}") from exc

        content_blocks = raw.get("content") or []
        text_parts: List[str] = []
        native_tool_calls: List[ToolCallRequest] = []
        for block in content_blocks:
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                # Anthropic provides `input` as a pre-parsed dict, not a JSON string.
                native_tool_calls.append(ToolCallRequest(
                    id=block["id"],
                    tool_name=block["name"],
                    tool_input=block.get("input", {}),
                ))

        text = "".join(text_parts)
        if not text and not native_tool_calls:
            raise RuntimeError("Anthropic API returned no content.")

        return LLMResponse(
            text=text,
            provider=self.provider_name,
            model=model,
            usage=raw.get("usage"),
            raw=raw,
            tool_calls=native_tool_calls,
        )

    def stream(
        self,
        *,
        api_key: str,
        model: str,
        prompt: str,
        system: Optional[str],
        params: Dict[str, Any],
        base_url: Optional[str],
        history: Optional[List[Dict[str, Any]]] = None,
        context: Optional[Dict[str, Any]] = None,
        timeout: int = DEFAULT_TIMEOUT,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Iterator[StreamChunk]:
        """Stream an LLM response from Anthropic, yielding chunks.

        Yields:
            StreamChunk objects as they arrive from the API.
        """
        if not api_key:
            raise ValueError("Missing Anthropic API key.")

        base = base_url or "https://api.anthropic.com/v1"
        url = base.rstrip("/") + "/messages"

        messages = _build_anthropic_messages(history, prompt)
        payload: Dict[str, Any] = {"model": model, "messages": messages, "stream": True}

        # Set max_tokens if not provided
        if "max_tokens" not in payload:
            payload["max_tokens"] = params.get("max_tokens", 1024)

        if system:
            payload["system"] = system

        payload.update({k: v for k, v in params.items() if v is not None and k != "stream"})

        if tools:
            payload["tools"] = [
                {
                    "name": tool["name"],
                    "description": tool["description"],
                    "input_schema": tool["parameters"],
                }
                for tool in tools
            ]

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with _urlopen_with_retry(req, timeout=timeout) as response:
                parser = SSEStreamParser()
                for line in response:
                    for event in parser.feed(line.decode("utf-8")):
                        yield self._anthropic_parse_event(event, model)
                for event in parser.flush():
                    yield self._anthropic_parse_event(event, model)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8") if exc.fp else ""
            try:
                error_data = json.loads(body)
                error_msg = error_data.get("error", {}).get("message", body)
            except json.JSONDecodeError:
                error_msg = body
            yield StreamChunk(
                chunk_type=StreamChunkType.ERROR,
                content=f"Anthropic API error: {error_msg}",
                provider=self.provider_name,
                model=model,
            )

    def _anthropic_parse_event(self, event: Dict[str, Any], model: str) -> StreamChunk:
        """Parse an Anthropic SSE event into a StreamChunk."""
        event_type = event.get("event", "")
        data = event.get("data", {})

        if not isinstance(data, dict):
            data = {}

        # Map Anthropic event types to our StreamChunkType
        if event_type == "message_start":
            return StreamChunk(
                chunk_type=StreamChunkType.START,
                provider=self.provider_name,
                model=model,
            )

        elif event_type == "content_block_start":
            content_block = data.get("content_block", {})
            block_type = content_block.get("type", "text")

            if block_type == "tool_use":
                return StreamChunk(
                    chunk_type=StreamChunkType.TOOL_CALL_START,
                    tool_name=content_block.get("name", "unknown"),
                    provider=self.provider_name,
                    model=model,
                )
            else:
                return StreamChunk(
                    chunk_type=StreamChunkType.START,
                    provider=self.provider_name,
                    model=model,
                )

        elif event_type == "content_block_delta":
            delta = data.get("delta", {})
            delta_type = delta.get("type", "")

            if delta_type == "text_delta":
                return StreamChunk(
                    chunk_type=StreamChunkType.CONTENT,
                    content=delta.get("text", ""),
                    provider=self.provider_name,
                    model=model,
                )

            elif delta_type == "input_json_delta":
                return StreamChunk(
                    chunk_type=StreamChunkType.TOOL_CALL_CHUNK,
                    tool_name=data.get("tool_name", "unknown"),
                    tool_input_chunk=delta.get("partial_json", ""),
                    provider=self.provider_name,
                    model=model,
                )

            else:
                return StreamChunk(
                    chunk_type=StreamChunkType.START,
                    provider=self.provider_name,
                    model=model,
                )

        elif event_type == "content_block_stop":
            return StreamChunk(
                chunk_type=StreamChunkType.TOOL_CALL_END,
                tool_name=data.get("tool_name", "unknown"),
                provider=self.provider_name,
                model=model,
            )

        elif event_type == "message_stop":
            return StreamChunk(
                chunk_type=StreamChunkType.STOP,
                provider=self.provider_name,
                model=model,
            )

        elif event_type == "error":
            return StreamChunk(
                chunk_type=StreamChunkType.ERROR,
                content=str(data),
                provider=self.provider_name,
                model=model,
            )

        else:
            return StreamChunk(
                chunk_type=StreamChunkType.START,
                provider=self.provider_name,
                model=model,
            )


class GeminiAdapter:
    """Adapter for the Gemini generateContent REST API.

    Native function calling is activated when ``tools`` is non-empty:
      - Adds ``"tools"`` (with ``function_declarations``) and ``"tool_config"``
        with ``mode: AUTO`` to the request body.
      - Parses ``functionCall`` parts from the response, populating
        ``LLMResponse.tool_calls`` with ``ToolCallRequest`` objects.
      - Translates ``_native_tool_calls`` / ``tool_results`` history entries
        into Gemini's ``functionCall`` / ``functionResponse`` part format.

    Note: Gemini does not assign unique IDs to function calls.  The tool name
    is used as the correlation ID (``ToolCallRequest.id = function_name``).
    This works correctly as long as the same tool is not called more than once
    in a single response turn.  If a model calls the same tool twice in one
    turn, results are correlated by position.  This is a Gemini API limitation.

    TODO(roadmap): Support streaming for token-level feedback.
    """

    provider_name = "gemini"

    _GEN_CONFIG_KEYS = {
        "temperature",
        "topP",
        "topK",
        "maxOutputTokens",
        "candidateCount",
        "stopSequences",
        "presencePenalty",
        "frequencyPenalty",
        "responseMimeType",
        "responseSchema",
        "responseJsonSchema",
        "thinkingConfig",
    }

    _PARAM_ALIASES = {
        "max_tokens": "maxOutputTokens",
        "max_output_tokens": "maxOutputTokens",
        "top_p": "topP",
        "top_k": "topK",
        "stop": "stopSequences",
        "stop_sequences": "stopSequences",
        "candidate_count": "candidateCount",
        "presence_penalty": "presencePenalty",
        "frequency_penalty": "frequencyPenalty",
        "response_mime_type": "responseMimeType",
        "response_schema": "responseSchema",
        "response_json_schema": "responseJsonSchema",
        "thinking_config": "thinkingConfig",
    }

    def call(
        self,
        *,
        api_key: str,
        model: str,
        prompt: str,
        system: Optional[str],
        params: Dict[str, Any],
        base_url: Optional[str],
        history: Optional[List[Dict[str, Any]]] = None,
        context: Optional[Dict[str, Any]] = None,
        timeout: int = DEFAULT_TIMEOUT,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        """Function implementation."""
        if not api_key:
            raise ValueError("Missing Gemini API key.")

        base = base_url or "https://generativelanguage.googleapis.com/v1beta"
        model_path = model if model.startswith("models/") else f"models/{model}"
        url = base.rstrip("/") + f"/{model_path}:generateContent"

        contents = _build_gemini_contents(history, prompt)

        body: Dict[str, Any] = {"contents": contents}
        if system:
            body["system_instruction"] = {"parts": [{"text": system}]}

        if tools:
            body["tools"] = [
                {
                    "function_declarations": [
                        {
                            "name": tool["name"],
                            "description": tool["description"],
                            "parameters": tool["parameters"],
                        }
                        for tool in tools
                    ]
                }
            ]
            body["tool_config"] = {"function_calling_config": {"mode": "AUTO"}}

        generation_config: Dict[str, Any] = {}
        params = dict(params or {})
        inline_config = params.pop("generationConfig", None)
        if isinstance(inline_config, dict):
            generation_config.update(inline_config)
        inline_config = params.pop("generation_config", None)
        if isinstance(inline_config, dict):
            generation_config.update(inline_config)

        for key, value in params.items():
            if value is None:
                continue
            target = self._PARAM_ALIASES.get(key, key)
            if target not in self._GEN_CONFIG_KEYS:
                continue
            if target == "stopSequences":
                if isinstance(value, str):
                    value = [value]
            generation_config[target] = value

        if generation_config:
            body["generationConfig"] = generation_config

        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "x-goog-api-key": api_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            raw = _urlopen_with_retry(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8") if exc.fp else ""
            raise RuntimeError(f"Gemini API error ({exc.code}): {body_text}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Gemini API request failed: {exc}") from exc

        candidates = raw.get("candidates") or []
        if not candidates:
            raise RuntimeError("Gemini API returned no candidates.")
        content = candidates[0].get("content") or {}
        parts = content.get("parts") or []

        text_parts: List[str] = []
        native_tool_calls: List[ToolCallRequest] = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            if part.get("text"):
                text_parts.append(part["text"])
            elif "functionCall" in part:
                fc = part["functionCall"]
                # Gemini has no per-call ID; use the function name as the
                # correlation handle (see class docstring for limitation note).
                native_tool_calls.append(ToolCallRequest(
                    id=fc.get("name", ""),
                    tool_name=fc["name"],
                    tool_input=fc.get("args", {}),
                ))

        text = "".join(text_parts)
        if not text and not native_tool_calls:
            raise RuntimeError("Gemini API returned no content.")

        return LLMResponse(
            text=text,
            provider=self.provider_name,
            model=model,
            usage=raw.get("usageMetadata") or raw.get("usage"),
            raw=raw,
            tool_calls=native_tool_calls,
        )

    def stream(
        self,
        *,
        api_key: str,
        model: str,
        prompt: str,
        system: Optional[str],
        params: Dict[str, Any],
        base_url: Optional[str],
        history: Optional[List[Dict[str, Any]]] = None,
        context: Optional[Dict[str, Any]] = None,
        timeout: int = DEFAULT_TIMEOUT,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Iterator[StreamChunk]:
        """Stream an LLM response from Gemini, yielding chunks.

        Note: Gemini's streaming API is less straightforward than OpenAI/Anthropic.
        This implementation yields START on stream begin and STOP on completion.

        Yields:
            StreamChunk objects as they arrive from the API.
        """
        if not api_key:
            raise ValueError("Missing Gemini API key.")

        base = base_url or "https://generativelanguage.googleapis.com/v1beta/openai"
        url = base.rstrip("/") + "/chat/completions"

        contents = _build_gemini_contents(history, prompt)
        payload: Dict[str, Any] = {
            "model": model,
            "contents": contents,
            "stream": True,
        }

        if system:
            payload["system_instruction"] = {"parts": [{"text": system}]}

        # Add tools if provided
        if tools:
            payload["tools"] = [
                {
                    "function_declarations": [
                        {
                            "name": tool["name"],
                            "description": tool.get("description", ""),
                            "parameters": tool["parameters"],
                        }
                        for tool in tools
                    ]
                }
            ]

        payload.update({k: v for k, v in params.items() if v is not None and k != "stream"})

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with _urlopen_with_retry(req, timeout=timeout) as response:
                yield StreamChunk(
                    chunk_type=StreamChunkType.START,
                    provider=self.provider_name,
                    model=model,
                )

                # Gemini streams JSON chunks, not SSE format
                for line in response:
                    try:
                        chunk_data = json.loads(line.decode("utf-8"))
                        # Parse Gemini response structure
                        for chunk in self._gemini_parse_chunks(chunk_data, model):
                            yield chunk
                    except json.JSONDecodeError:
                        continue

                yield StreamChunk(
                    chunk_type=StreamChunkType.STOP,
                    provider=self.provider_name,
                    model=model,
                )
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8") if exc.fp else ""
            try:
                error_data = json.loads(body)
                error_msg = error_data.get("error", {}).get("message", body)
            except json.JSONDecodeError:
                error_msg = body
            yield StreamChunk(
                chunk_type=StreamChunkType.ERROR,
                content=f"Gemini API error: {error_msg}",
                provider=self.provider_name,
                model=model,
            )

    def _gemini_parse_chunks(self, chunk_data: Dict[str, Any], model: str) -> Iterator[StreamChunk]:
        """Parse Gemini streaming chunks into StreamChunk objects."""
        candidates = chunk_data.get("candidates", [])
        if not candidates:
            return

        content = candidates[0].get("content", {})
        parts = content.get("parts", [])

        for part in parts:
            if "text" in part and part["text"]:
                yield StreamChunk(
                    chunk_type=StreamChunkType.CONTENT,
                    content=part["text"],
                    provider=self.provider_name,
                    model=model,
                )

            elif "functionCall" in part:
                fc = part["functionCall"]
                tool_name = fc.get("name", "unknown")
                args = fc.get("args", {})

                yield StreamChunk(
                    chunk_type=StreamChunkType.TOOL_CALL_START,
                    tool_name=tool_name,
                    provider=self.provider_name,
                    model=model,
                )

                yield StreamChunk(
                    chunk_type=StreamChunkType.TOOL_CALL_CHUNK,
                    tool_name=tool_name,
                    tool_input_chunk=json.dumps(args),
                    provider=self.provider_name,
                    model=model,
                )

                yield StreamChunk(
                    chunk_type=StreamChunkType.TOOL_CALL_END,
                    tool_name=tool_name,
                    provider=self.provider_name,
                    model=model,
                )
