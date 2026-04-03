"""Tests for LLMClient runtime controls (rate limit and per-run budgets)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest

from agent_runtime.llm import LLMRegistry, LLMProvider, ModelConfig
from agent_runtime.llm.client import LLMClient
from agent_runtime.llm.types import LLMResponse


class StubAdapter:
    provider_name = "openai"

    def __init__(self, responses: Optional[List[LLMResponse]] = None) -> None:
        """Function implementation."""
        self._responses = list(responses or [])
        self.calls = 0

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
        timeout: int = 60,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        """Function implementation."""
        self.calls += 1
        if self._responses:
            return self._responses.pop(0)
        return LLMResponse(
            text="ok",
            provider="openai",
            model=model,
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            raw={},
        )


def _client(adapter: StubAdapter, **kwargs: Any) -> LLMClient:
    """Function implementation."""
    registry = LLMRegistry()
    provider = LLMProvider(name="openai", api_key_env="TEST_OPENAI_KEY")
    provider.add_model(ModelConfig(model_id="gpt-4o"))
    registry.register_provider(provider)
    return LLMClient(registry=registry, adapters={"openai": adapter}, **kwargs)


def test_max_requests_per_run_is_enforced_pre_call() -> None:
    """Function implementation."""
    adapter = StubAdapter()
    client = _client(adapter, max_requests_per_run=1)

    with patch.dict("os.environ", {"TEST_OPENAI_KEY": "x"}):
        first = client.call(model="openai/gpt-4o", prompt="first", context={"run_id": "run-1"})
        assert first.text == "ok"

        with pytest.raises(RuntimeError, match="request budget exceeded"):
            client.call(model="openai/gpt-4o", prompt="second", context={"run_id": "run-1"})

    assert adapter.calls == 1


def test_max_total_tokens_per_run_is_enforced() -> None:
    """Function implementation."""
    adapter = StubAdapter(
        responses=[
            LLMResponse(
                text="a",
                provider="openai",
                model="gpt-4o",
                usage={"prompt_tokens": 4, "completion_tokens": 4, "total_tokens": 8},
                raw={},
            ),
            LLMResponse(
                text="b",
                provider="openai",
                model="gpt-4o",
                usage={"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
                raw={},
            ),
        ]
    )
    client = _client(adapter, max_total_tokens_per_run=10)

    with patch.dict("os.environ", {"TEST_OPENAI_KEY": "x"}):
        client.call(model="openai/gpt-4o", prompt="first", context={"run_id": "run-2"})
        with pytest.raises(RuntimeError, match="token budget exceeded"):
            client.call(model="openai/gpt-4o", prompt="second", context={"run_id": "run-2"})

    assert adapter.calls == 2


def test_max_cost_usd_per_run_uses_configured_pricing() -> None:
    """Function implementation."""
    adapter = StubAdapter(
        responses=[
            LLMResponse(
                text="a",
                provider="openai",
                model="gpt-4o",
                usage={"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200},
                raw={},
            ),
        ]
    )
    client = _client(
        adapter,
        max_cost_usd_per_run=0.05,
        pricing_usd_per_1k_tokens={
            "openai/gpt-4o": {
                "input": 0.30,
                "output": 0.30,
            }
        },
    )

    with patch.dict("os.environ", {"TEST_OPENAI_KEY": "x"}):
        with pytest.raises(RuntimeError, match="cost budget exceeded"):
            client.call(model="openai/gpt-4o", prompt="first", context={"run_id": "run-3"})

    assert adapter.calls == 1


def test_rate_limit_rpm_throttles_calls() -> None:
    """Function implementation."""
    adapter = StubAdapter()
    client = _client(adapter, rate_limit_rpm=1)

    with patch.dict("os.environ", {"TEST_OPENAI_KEY": "x"}):
        with patch("agent_runtime.llm.client.time.monotonic", side_effect=[0.0, 0.1, 60.2]):
            with patch("agent_runtime.llm.client.time.sleep") as sleep_mock:
                client.call(model="openai/gpt-4o", prompt="one", context={"run_id": "run-4"})
                client.call(model="openai/gpt-4o", prompt="two", context={"run_id": "run-4"})

    sleep_mock.assert_called_once()
    assert sleep_mock.call_args[0][0] > 59.0
    assert adapter.calls == 2


def test_usage_normalization_supports_gemini_shape() -> None:
    """Function implementation."""
    adapter = StubAdapter(
        responses=[
            LLMResponse(
                text="gemini",
                provider="openai",
                model="gpt-4o",
                usage={"promptTokenCount": 6, "candidatesTokenCount": 5},
                raw={},
            )
        ]
    )
    client = _client(adapter, max_total_tokens_per_run=10)

    with patch.dict("os.environ", {"TEST_OPENAI_KEY": "x"}):
        with pytest.raises(RuntimeError, match="token budget exceeded"):
            client.call(model="openai/gpt-4o", prompt="x", context={"run_id": "run-5"})

    assert adapter.calls == 1
