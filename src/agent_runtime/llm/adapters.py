from __future__ import annotations

"""LLM adapter implementations (HTTP clients per provider)."""

from typing import Any, Dict, Optional, Protocol
import json
import urllib.error
import urllib.request

from .types import LLMResponse


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
        context: Optional[Dict[str, Any]],
    ) -> LLMResponse:
        """Execute an LLM request and return a normalized response."""
        ...


class OpenAIAdapter:
    """Minimal OpenAI-compatible adapter using the Chat Completions API.

    TODO: Support the newer Responses API and streaming for better token-level feedback.
    TODO: Add explicit timeouts and retry/backoff for transient HTTP errors.
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
        context: Optional[Dict[str, Any]],
    ) -> LLMResponse:
        if not api_key:
            raise ValueError("Missing OpenAI API key.")

        base = base_url or "https://api.openai.com/v1"
        url = base.rstrip("/") + "/chat/completions"

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
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
            with urllib.request.urlopen(req) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
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
