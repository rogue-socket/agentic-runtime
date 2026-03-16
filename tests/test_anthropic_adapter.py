"""Tests for the Anthropic LLM adapter."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional
from unittest.mock import patch, MagicMock

from agent_runtime.llm.adapters import AnthropicAdapter
from agent_runtime.llm.types import LLMResponse
from agent_runtime.llm.client import LLMClient
from agent_runtime.llm import LLMRegistry, LLMProvider, ModelConfig

import pytest


# ---------------------------------------------------------------------------
# AnthropicAdapter unit tests
# ---------------------------------------------------------------------------


def _mock_anthropic_response(text: str = "Hello!", usage: Optional[Dict] = None) -> bytes:
    body = {
        "content": [{"type": "text", "text": text}],
        "model": "claude-3-opus",
        "usage": usage or {"input_tokens": 10, "output_tokens": 5},
    }
    return json.dumps(body).encode("utf-8")


def test_anthropic_adapter_call_success() -> None:
    adapter = AnthropicAdapter()
    mock_resp = MagicMock()
    mock_resp.read.return_value = _mock_anthropic_response("Test output")
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = adapter.call(
            api_key="sk-ant-test",
            model="claude-3-opus",
            prompt="Say hello",
            system=None,
            params={},
            base_url=None,
            context=None,
        )

    assert isinstance(result, LLMResponse)
    assert result.text == "Test output"
    assert result.provider == "anthropic"
    assert result.model == "claude-3-opus"


def test_anthropic_adapter_with_system_prompt() -> None:
    adapter = AnthropicAdapter()
    mock_resp = MagicMock()
    mock_resp.read.return_value = _mock_anthropic_response("With system")
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        result = adapter.call(
            api_key="sk-ant-test",
            model="claude-3-opus",
            prompt="Hi",
            system="You are helpful.",
            params={"temperature": 0.5},
            base_url=None,
            context=None,
        )

    assert result.text == "With system"
    # Verify the request was made
    mock_urlopen.assert_called_once()
    req = mock_urlopen.call_args[0][0]
    body = json.loads(req.data.decode("utf-8"))
    assert body["system"] == "You are helpful."
    assert body["temperature"] == 0.5


def test_anthropic_adapter_missing_key() -> None:
    adapter = AnthropicAdapter()
    with pytest.raises(ValueError, match="Missing Anthropic API key"):
        adapter.call(
            api_key="",
            model="claude-3-opus",
            prompt="Hi",
            system=None,
            params={},
            base_url=None,
            context=None,
        )


def test_anthropic_adapter_custom_base_url() -> None:
    adapter = AnthropicAdapter()
    mock_resp = MagicMock()
    mock_resp.read.return_value = _mock_anthropic_response("custom")
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        adapter.call(
            api_key="sk-test",
            model="claude-3",
            prompt="test",
            system=None,
            params={},
            base_url="https://custom.api.com",
            context=None,
        )

    req = mock_urlopen.call_args[0][0]
    assert req.full_url == "https://custom.api.com/v1/messages"


def test_anthropic_adapter_empty_content_raises() -> None:
    adapter = AnthropicAdapter()
    body = json.dumps({"content": [], "model": "claude-3-opus"}).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="no text content"):
            adapter.call(
                api_key="sk-test",
                model="claude-3-opus",
                prompt="test",
                system=None,
                params={},
                base_url=None,
                context=None,
            )


# ---------------------------------------------------------------------------
# LLMClient integration with Anthropic
# ---------------------------------------------------------------------------


def test_client_routes_to_anthropic() -> None:
    registry = LLMRegistry()
    provider = LLMProvider(name="anthropic", api_key_env="ANTHROPIC_API_KEY")
    provider.add_model(ModelConfig(model_id="claude-3-opus"))
    registry.register_provider(provider)

    mock_adapter = MagicMock()
    mock_adapter.provider_name = "anthropic"
    mock_adapter.call.return_value = LLMResponse(
        text="Routed", provider="anthropic", model="claude-3-opus"
    )

    client = LLMClient(
        registry=registry,
        adapters={"anthropic": mock_adapter},
    )

    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-test"}):
        response = client.call(model="anthropic/claude-3-opus", prompt="Hello")

    assert response.text == "Routed"
    mock_adapter.call.assert_called_once()


def test_client_resolves_provider_slash_model() -> None:
    registry = LLMRegistry()
    provider = LLMProvider(name="anthropic", api_key_env="ANTHROPIC_API_KEY")
    provider.add_model(ModelConfig(model_id="claude-3-opus"))
    registry.register_provider(provider)

    mock_adapter = MagicMock()
    mock_adapter.provider_name = "anthropic"
    mock_adapter.call.return_value = LLMResponse(
        text="ok", provider="anthropic", model="claude-3-opus"
    )

    client = LLMClient(registry=registry, adapters={"anthropic": mock_adapter})

    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}):
        response = client.call(model="anthropic/claude-3-opus", prompt="test")

    assert response.provider == "anthropic"
    assert response.model == "claude-3-opus"
