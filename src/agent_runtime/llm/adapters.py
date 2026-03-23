from __future__ import annotations

"""LLM adapter implementations (HTTP clients per provider)."""

from typing import Any, Dict, List, Optional, Protocol
import json
import time
import urllib.error
import urllib.request

from .types import LLMResponse

# Default HTTP timeout in seconds.
DEFAULT_TIMEOUT: int = 60

# Default retry config for transient HTTP errors (429, 500, 502, 503, 504).
DEFAULT_MAX_RETRIES: int = 2
DEFAULT_INITIAL_DELAY: float = 1.0

_RETRYABLE_CODES = frozenset({429, 500, 502, 503, 504})


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
    raise last_exc  # type: ignore[misc]  # unreachable in practice


# [Pain Point Solved] #5 Framework Lock-in / Dependency Hell: Provider-agnostic
#   Protocol — any backend implements call(). All adapters use stdlib urllib, so
#   zero SDK dependencies. Swapping OpenAI for Gemini is a config change, not a refactor.
# ---------------------------------------------------------------------------
# TODO(native-function-calling — Phase 2: Adapter Protocol Extension)
#
# To support native function calling, extend the `LLMAdapter.call()` signature
# with a `tools` parameter. This carries the JSON Schema definitions of the
# tools to register with the model.
#
# WHAT TO DO:
#   1. Add `tools: Optional[List[Dict[str, Any]]] = None` to `call()` here.
#      Each entry is a provider-agnostic tool schema:
#        {
#            "name": str,              # tool name
#            "description": str,       # what it does
#            "parameters": {...}       # JSON Schema of the input
#        }
#   2. Each concrete adapter translates this into its own wire format
#      (see OpenAI, Anthropic, Gemini TODOs below).
#   3. The `LLMResponse` already has `tool_calls: List[ToolCallRequest]`.
#      Adapters should populate it when the model responds with function calls
#      instead of (or alongside) text.
#   4. `LLMClient.call()` passes `tools` through to the adapter unchanged.
#   5. `strategies.py` checks `response.tool_calls` BEFORE falling back to
#      the text parser — see TODO there.
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
        history: Optional[List[Dict[str, str]]] = None,
        context: Optional[Dict[str, Any]] = None,
        timeout: int = DEFAULT_TIMEOUT,
        # TODO(native-function-calling): add tools: Optional[List[Dict[str, Any]]] = None
    ) -> LLMResponse:
        """Execute an LLM request and return a normalized response."""
        ...


class OpenAIAdapter:
    """Minimal OpenAI-compatible adapter using the Chat Completions API.

    TODO(native-function-calling — OpenAI): Implement native function calling
    via the Chat Completions `tools` parameter.

    REQUEST CHANGES:
      Add to the payload dict:
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["parameters"],  # JSON Schema
                }
            }
            for tool in tools
        ],
        "tool_choice": "auto",  # let the model decide

    RESPONSE CHANGES:
      The `choices[0].message` can have `tool_calls` instead of (or with) `content`.
      Parse each element:
        for tc in (message.get("tool_calls") or []):
            ToolCallRequest(
                id=tc["id"],
                tool_name=tc["function"]["name"],
                tool_input=json.loads(tc["function"]["arguments"]),
            )
      Set `LLMResponse.tool_calls` to the parsed list.
      Set `LLMResponse.text` to `message.get("content") or ""`.

    FOLLOW-UP TURN:
      When sending tool results back, add a message per call:
        {"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)}
      The history-building logic in `strategies.py` needs updating too.

    TODO: Support streaming (stream=True) for token-level feedback.
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
        history: Optional[List[Dict[str, str]]] = None,
        context: Optional[Dict[str, Any]] = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> LLMResponse:
        if not api_key:
            raise ValueError("Missing OpenAI API key.")

        base = base_url or "https://api.openai.com/v1"
        url = base.rstrip("/") + "/chat/completions"

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model,
            "messages": messages,
        }
        payload.update({k: v for k, v in params.items() if v is not None})

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
        content = (choices[0].get("message") or {}).get("content")
        if not isinstance(content, str):
            raise RuntimeError("OpenAI API returned an empty response message.")

        return LLMResponse(
            text=content,
            provider=self.provider_name,
            model=model,
            usage=raw.get("usage"),
            raw=raw,
        )


class AnthropicAdapter:
    """Adapter for the Anthropic Messages API.

    TODO(native-function-calling — Anthropic): Implement native tool use
    via the Messages API `tools` parameter.

    REQUEST CHANGES:
      Add to the body dict:
        "tools": [
            {
                "name": tool["name"],
                "description": tool["description"],
                "input_schema": tool["parameters"],  # JSON Schema
            }
            for tool in tools
        ],

    RESPONSE CHANGES:
      The response `content` list can contain blocks of type `"tool_use"` in
      addition to `"text"` blocks. Parse each:
        for block in content_blocks:
            if block.get("type") == "tool_use":
                ToolCallRequest(
                    id=block["id"],
                    tool_name=block["name"],
                    tool_input=block["input"],  # already a dict, not a string
                )
      Set `LLMResponse.tool_calls` to the parsed list.
      Set `LLMResponse.text` to joined text blocks as now.

    FOLLOW-UP TURN:
      Add a `tool_result` block to the next user message:
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": json.dumps(result),
                }
            ]
        }
      The history-building logic in `strategies.py` needs updating too.

    TODO: Add streaming support for token-level feedback.
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
        history: Optional[List[Dict[str, str]]] = None,
        context: Optional[Dict[str, Any]] = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> LLMResponse:
        if not api_key:
            raise ValueError("Missing Anthropic API key.")

        base = base_url or "https://api.anthropic.com"
        url = base.rstrip("/") + "/v1/messages"

        messages = []
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})

        body: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": params.pop("max_tokens", 4096),
        }
        if system:
            body["system"] = system
        body.update({k: v for k, v in params.items() if v is not None})

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
        text_parts = [
            block.get("text", "")
            for block in content_blocks
            if block.get("type") == "text"
        ]
        if not text_parts:
            raise RuntimeError("Anthropic API returned no text content.")

        return LLMResponse(
            text="".join(text_parts),
            provider=self.provider_name,
            model=model,
            usage=raw.get("usage"),
            raw=raw,
        )


class GeminiAdapter:
    """Adapter for the Gemini generateContent REST API.

    TODO(native-function-calling — Gemini): Implement native function calling
    via the `tools` + `tool_config` fields in the generateContent request.

    REQUEST CHANGES:
      Add to the body dict:
        "tools": [
            {
                "function_declarations": [
                    {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["parameters"],  # JSON Schema
                    }
                    for tool in tools
                ]
            }
        ],
        "tool_config": {"function_calling_config": {"mode": "AUTO"}},

    RESPONSE CHANGES:
      The `parts` list in `candidates[0].content` can contain `functionCall`
      dicts instead of (or with) `text` dicts. Parse each:
        for part in parts:
            if "functionCall" in part:
                ToolCallRequest(
                    id=part["functionCall"].get("name", ""),  # Gemini uses name as ID
                    tool_name=part["functionCall"]["name"],
                    tool_input=part["functionCall"].get("args", {}),
                )
      Set `LLMResponse.tool_calls` to the parsed list.
      Set `LLMResponse.text` to joined text parts as now.

    FOLLOW-UP TURN:
      Add a `functionResponse` part to the next user content:
        {
            "role": "user",
            "parts": [
                {
                    "functionResponse": {
                        "name": tc.tool_name,
                        "response": {"result": result},
                    }
                }
            ]
        }
      The history-building logic in `strategies.py` needs updating too.
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
        history: Optional[List[Dict[str, str]]] = None,
        context: Optional[Dict[str, Any]] = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> LLMResponse:
        if not api_key:
            raise ValueError("Missing Gemini API key.")

        base = base_url or "https://generativelanguage.googleapis.com/v1beta"
        model_path = model if model.startswith("models/") else f"models/{model}"
        url = base.rstrip("/") + f"/{model_path}:generateContent"

        contents = []
        if history:
            for msg in history:
                role = "model" if msg.get("role") == "assistant" else "user"
                contents.append({"role": role, "parts": [{"text": msg.get("content", "")}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        body: Dict[str, Any] = {
            "contents": contents
        }
        if system:
            body["system_instruction"] = {"parts": [{"text": system}]}

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
        text_parts = [
            part.get("text", "")
            for part in parts
            if isinstance(part, dict) and part.get("text")
        ]
        if not text_parts:
            raise RuntimeError("Gemini API returned no text content.")

        return LLMResponse(
            text="".join(text_parts),
            provider=self.provider_name,
            model=model,
            usage=raw.get("usageMetadata") or raw.get("usage"),
            raw=raw,
        )
