"""Tests for guided ConfigValidationError messages from LLMClient."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest

from agent_runtime.errors import ConfigValidationError, get_error_code
from agent_runtime.llm import LLMRegistry, LLMProvider, ModelConfig
from agent_runtime.llm.client import LLMClient
from agent_runtime.llm.types import LLMResponse


class StubAdapter:
    provider_name = "openai"

    def call(self, **kwargs: Any) -> LLMResponse:
        return LLMResponse(text="ok", provider="openai", model=kwargs["model"], usage=None)


def _client_with_provider(adapter: Optional[StubAdapter] = None) -> LLMClient:
    registry = LLMRegistry()
    provider = LLMProvider(name="openai", api_key_env="OPENAI_API_KEY")
    provider.add_model(ModelConfig(model_id="gpt-4o"))
    registry.register_provider(provider)
    adapters = {"openai": adapter} if adapter else None
    return LLMClient(registry=registry, adapters=adapters or {"openai": StubAdapter()})


def test_unregistered_provider_raises_guided_config_error() -> None:
    registry = LLMRegistry()  # no providers registered
    client = LLMClient(registry=registry, adapters={"openai": StubAdapter()})

    with pytest.raises(ConfigValidationError) as excinfo:
        client.call(model="openai/gpt-4o", prompt="hi")

    msg = str(excinfo.value)
    assert "openai" in msg
    assert "not registered" in msg
    assert "ai config --provider openai" in msg
    assert get_error_code(excinfo.value) == "AR-CONFIG-VALIDATION"


def test_missing_api_key_raises_guided_config_error() -> None:
    client = _client_with_provider()
    # Ensure the env var is unset
    with patch.dict("os.environ", {}, clear=False):
        import os
        os.environ.pop("OPENAI_API_KEY", None)
        with pytest.raises(ConfigValidationError) as excinfo:
            client.call(model="openai/gpt-4o", prompt="hi")

    msg = str(excinfo.value)
    assert "OPENAI_API_KEY" in msg
    assert ".env" in msg
    assert "ai config --provider openai" in msg
    assert get_error_code(excinfo.value) == "AR-CONFIG-VALIDATION"


def test_missing_adapter_raises_guided_config_error() -> None:
    registry = LLMRegistry()
    provider = LLMProvider(name="openai", api_key_env="OPENAI_API_KEY")
    provider.add_model(ModelConfig(model_id="gpt-4o"))
    registry.register_provider(provider)
    # Pass a non-empty adapters dict that intentionally lacks the openai adapter.
    # (An empty dict is falsy and would fall back to the full default set.)
    client = LLMClient(registry=registry, adapters={"placeholder": StubAdapter()})

    with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-x"}):
        with pytest.raises(ConfigValidationError) as excinfo:
            client.call(model="openai/gpt-4o", prompt="hi")

    msg = str(excinfo.value)
    assert "openai" in msg
    assert "Supported:" in msg
    assert get_error_code(excinfo.value) == "AR-CONFIG-VALIDATION"


def test_mock_provider_does_not_require_api_key() -> None:
    """Mock provider should still work without an env var (regression guard)."""
    from agent_runtime.llm.adapters import MockAdapter

    registry = LLMRegistry()
    provider = LLMProvider(name="mock", api_key_env="MOCK_KEY_NOT_SET")
    provider.add_model(ModelConfig(model_id="mock-model"))
    registry.register_provider(provider)
    client = LLMClient(registry=registry, adapters={"mock": MockAdapter()})

    # Should not raise even though MOCK_KEY_NOT_SET is unset.
    resp = client.call(model="mock/mock-model", prompt="hi")
    assert resp.provider == "mock"
