from __future__ import annotations

"""LLM client that routes requests through provider adapters."""

from collections import deque
import threading
import time
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
        rate_limit_rpm: int = 0,
        max_requests_per_run: int = 0,
        max_total_tokens_per_run: int = 0,
        max_cost_usd_per_run: float = 0.0,
        pricing_usd_per_1k_tokens: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> None:
        self.registry = registry
        self.logger = logger
        self.adapters = adapters or {
            OpenAIAdapter.provider_name: OpenAIAdapter(),
            AnthropicAdapter.provider_name: AnthropicAdapter(),
            GeminiAdapter.provider_name: GeminiAdapter(),
            MockAdapter.provider_name: MockAdapter(),
        }
        self.rate_limit_rpm = max(0, int(rate_limit_rpm))
        self.max_requests_per_run = max(0, int(max_requests_per_run))
        self.max_total_tokens_per_run = max(0, int(max_total_tokens_per_run))
        self.max_cost_usd_per_run = max(0.0, float(max_cost_usd_per_run))
        self.pricing_usd_per_1k_tokens = pricing_usd_per_1k_tokens or {}

        self._lock = threading.Lock()
        self._request_timestamps: deque[float] = deque()
        self._run_usage: Dict[str, Dict[str, float]] = {}

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
        run_id = str((context or {}).get("run_id") or "__default__")

        self._enforce_rate_limit()
        self._enforce_pre_call_limits(run_id)

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

        self._record_usage_and_enforce_post_call_limits(
            run_id=run_id,
            provider=provider_name,
            model=model_id,
            usage=response.usage,
        )

        return response

    def _enforce_rate_limit(self) -> None:
        """Throttle outgoing LLM calls to configured requests-per-minute."""
        if self.rate_limit_rpm <= 0:
            return

        window_s = 60.0
        while True:
            sleep_for = 0.0
            now = time.monotonic()
            with self._lock:
                while self._request_timestamps and (now - self._request_timestamps[0]) >= window_s:
                    self._request_timestamps.popleft()

                if len(self._request_timestamps) < self.rate_limit_rpm:
                    self._request_timestamps.append(now)
                    return

                sleep_for = window_s - (now - self._request_timestamps[0])

            if sleep_for > 0:
                time.sleep(sleep_for)

    def _get_or_create_usage(self, run_id: str) -> Dict[str, float]:
        """Load or initialize usage counters for a run id."""
        usage = self._run_usage.get(run_id)
        if usage is not None:
            return usage
        usage = {
            "requests": 0.0,
            "input_tokens": 0.0,
            "output_tokens": 0.0,
            "total_tokens": 0.0,
            "cost_usd": 0.0,
        }
        self._run_usage[run_id] = usage
        return usage

    def _enforce_pre_call_limits(self, run_id: str) -> None:
        """Fail fast when a run has already exhausted hard pre-call budgets."""
        with self._lock:
            usage = self._get_or_create_usage(run_id)
            requests = int(usage["requests"])
            total_tokens = int(usage["total_tokens"])
            cost_usd = float(usage["cost_usd"])

        if self.max_requests_per_run > 0 and requests >= self.max_requests_per_run:
            raise RuntimeError(
                f"LLM request budget exceeded for run '{run_id}': "
                f"{requests}/{self.max_requests_per_run} requests used."
            )

        if self.max_total_tokens_per_run > 0 and total_tokens >= self.max_total_tokens_per_run:
            raise RuntimeError(
                f"LLM token budget exceeded for run '{run_id}': "
                f"{total_tokens}/{self.max_total_tokens_per_run} total tokens used."
            )

        if self.max_cost_usd_per_run > 0 and cost_usd >= self.max_cost_usd_per_run:
            raise RuntimeError(
                f"LLM cost budget exceeded for run '{run_id}': "
                f"${cost_usd:.6f}/${self.max_cost_usd_per_run:.6f} used."
            )

    def _record_usage_and_enforce_post_call_limits(
        self,
        *,
        run_id: str,
        provider: str,
        model: str,
        usage: Optional[Dict[str, Any]],
    ) -> None:
        """Accumulate usage after a call and enforce token/cost limits."""
        input_tokens, output_tokens, total_tokens = self._normalize_token_usage(usage)
        estimated_cost = self._estimate_cost_usd(provider, model, input_tokens, output_tokens)

        with self._lock:
            counters = self._get_or_create_usage(run_id)
            counters["requests"] += 1.0
            counters["input_tokens"] += float(input_tokens)
            counters["output_tokens"] += float(output_tokens)
            counters["total_tokens"] += float(total_tokens)
            if estimated_cost is not None:
                counters["cost_usd"] += float(estimated_cost)

            requests = int(counters["requests"])
            cumulative_tokens = int(counters["total_tokens"])
            cumulative_cost = float(counters["cost_usd"])

        if self.max_total_tokens_per_run > 0 and cumulative_tokens > self.max_total_tokens_per_run:
            raise RuntimeError(
                f"LLM token budget exceeded for run '{run_id}' after request {requests}: "
                f"{cumulative_tokens}/{self.max_total_tokens_per_run} total tokens used."
            )

        if self.max_cost_usd_per_run > 0 and cumulative_cost > self.max_cost_usd_per_run:
            raise RuntimeError(
                f"LLM cost budget exceeded for run '{run_id}' after request {requests}: "
                f"${cumulative_cost:.6f}/${self.max_cost_usd_per_run:.6f} used."
            )

    @staticmethod
    def _to_int(value: Any) -> int:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return int(value)
        return 0

    def _normalize_token_usage(self, usage: Optional[Dict[str, Any]]) -> Tuple[int, int, int]:
        """Normalize provider-specific usage objects into input/output/total tokens."""
        if not isinstance(usage, dict):
            return (0, 0, 0)

        input_tokens = self._to_int(
            usage.get("input_tokens", usage.get("prompt_tokens", usage.get("promptTokenCount", 0)))
        )
        output_tokens = self._to_int(
            usage.get("output_tokens", usage.get("completion_tokens", usage.get("candidatesTokenCount", 0)))
        )
        total_tokens = self._to_int(usage.get("total_tokens", usage.get("totalTokenCount", 0)))
        if total_tokens <= 0:
            total_tokens = input_tokens + output_tokens
        return (input_tokens, output_tokens, total_tokens)

    def _estimate_cost_usd(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> Optional[float]:
        """Estimate request cost using configured per-1k token pricing."""
        if not self.pricing_usd_per_1k_tokens:
            return None

        price_cfg = (
            self.pricing_usd_per_1k_tokens.get(f"{provider}/{model}")
            or self.pricing_usd_per_1k_tokens.get(f"{provider}/*")
            or self.pricing_usd_per_1k_tokens.get("*")
        )
        if not isinstance(price_cfg, dict):
            return None

        input_rate = float(price_cfg.get("input", 0.0))
        output_rate = float(price_cfg.get("output", input_rate))

        return ((input_tokens / 1000.0) * input_rate) + ((output_tokens / 1000.0) * output_rate)

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
