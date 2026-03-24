from __future__ import annotations

"""LLM client that routes requests through provider adapters."""

from typing import Any, Dict, List, Optional, Tuple

from .adapters import LLMAdapter, OpenAIAdapter, AnthropicAdapter, GeminiAdapter, MockAdapter
from .registry import LLMRegistry
from .types import LLMResponse
from ..logging import StructuredLogger


class LLMClient:
    """Client facade that resolves providers/models and executes calls."""

    # TODO(pain-point): Rate Limiting Across Concurrent Runs - One
    #   workflow is fine. Fifty concurrent webhook-triggered runs all hit the
    #   same provider and get rate-limited together. Add a global rate limiter
    #   (token bucket or semaphore) at this client level so concurrent
    #   Executor instances share a throttled request queue instead of each
    #   independently hammering the API and triggering 429s.
    # TODO(pain-point): Model Regression Detection - When you swap
    #   from gpt-4o-2024-05-13 to gpt-4o-2024-08-06, nothing breaks but
    #   output quality subtly shifts. Add a `compare_models()` utility that
    #   runs the same inputs through two model versions and diffs outputs
    #   (semantic similarity, key presence, format adherence) to catch
    #   regressions before they reach production.
    def __init__(
        self,
        registry: LLMRegistry,
        logger: Optional[StructuredLogger] = None,
        adapters: Optional[Dict[str, LLMAdapter]] = None,
    ) -> None:
        self.registry = registry
        self.logger = logger
        self.adapters = adapters or {
            OpenAIAdapter.provider_name: OpenAIAdapter(),
            AnthropicAdapter.provider_name: AnthropicAdapter(),
            GeminiAdapter.provider_name: GeminiAdapter(),
            MockAdapter.provider_name: MockAdapter(),
        }

    def call(
        self,
        *,
        model: str,
        prompt: str,
        provider: Optional[str] = None,
        system: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        params: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        """Resolve provider/model and invoke the matching adapter.

        Args:
            tools: Provider-agnostic tool schema list for native function calling.
                   Each entry: ``{"name": str, "description": str, "parameters": JSON Schema}``.
                   Built by ``strategies._build_tool_schemas()`` from the agent's tool registry.
                   Pass ``None`` to disable native function calling (text-based fallback).
        """

        provider_name, model_id = self._resolve_provider_model(provider, model)
        provider_obj = self.registry.get_provider(provider_name)
        if provider_obj is None:
            raise ValueError(f"LLM provider not configured: {provider_name}")

        api_key = provider_obj.resolve_api_key()
        if not api_key and provider_name != "mock":
            raise ValueError(f"API key env var '{provider_obj.api_key_env}' is not set")
        
        # Handle mock provider with a synthetic key if not provided
        api_key = api_key or "mock-key"

        adapter = self.adapters.get(provider_name)
        if adapter is None:
            raise ValueError(f"No adapter registered for provider: {provider_name}")

        model_cfg = provider_obj.get_model(model_id)
        merged_params: Dict[str, Any] = {}
        timeout: int = 60  # default
        if model_cfg is not None:
            merged_params["temperature"] = model_cfg.temperature
            merged_params["max_tokens"] = model_cfg.max_tokens
            timeout = model_cfg.timeout
            merged_params.update(model_cfg.extra)

        if params:
            merged_params.update(params)

        if self.logger:
            self.logger.info(
                "LLM_START",
                {
                    "provider": provider_name,
                    "model": model_id,
                    "run_id": (context or {}).get("run_id"),
                    "step_id": (context or {}).get("step_id"),
                },
            )

        try:
            response = adapter.call(
                api_key=api_key,
                model=model_id,
                prompt=prompt,
                system=system,
                params=merged_params,
                base_url=provider_obj.base_url,
                history=history,
                context=context,
                timeout=timeout,
                tools=tools,
            )
        except Exception as exc:  # noqa: BLE001
            if self.logger:
                self.logger.error(
                    "LLM_ERROR",
                    {
                        "provider": provider_name,
                        "model": model_id,
                        "run_id": (context or {}).get("run_id"),
                        "step_id": (context or {}).get("step_id"),
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )
            raise

        if self.logger:
            self.logger.info(
                "LLM_SUCCESS",
                {
                    "provider": provider_name,
                    "model": model_id,
                    "run_id": (context or {}).get("run_id"),
                    "step_id": (context or {}).get("step_id"),
                    "usage": response.usage,
                },
            )

        return response

    def _resolve_provider_model(self, provider: Optional[str], model: str) -> Tuple[str, str]:
        """Resolve provider/model from explicit values or a provider/model string."""
        if provider:
            return provider, model

        if "/" in model:
            provider_name, model_id = model.split("/", 1)
            if not provider_name or not model_id:
                raise ValueError(f"Invalid model reference: {model}")
            return provider_name, model_id

        providers = self.registry.list_providers()
        if self.registry.default_provider:
            return self.registry.default_provider, model
        if len(providers) == 1:
            return providers[0], model

        raise ValueError("Provider not specified and multiple providers are configured. "
                         "Set default_llm_provider in runtime.yaml or use provider/model syntax.")
