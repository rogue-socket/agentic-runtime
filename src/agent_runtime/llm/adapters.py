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
    ) -> LLMResponse:
        """Execute an LLM request and return a normalized response."""
        ...


class OpenAIAdapter:
    """Minimal OpenAI-compatible adapter using the Chat Completions API.

    TODO: Support the newer Responses API and streaming for better token-level feedback.
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
    """Adapter for the Gemini generateContent REST API."""

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
