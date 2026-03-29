"""Tests for the Gemini LLM adapter."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

from agent_runtime.llm.adapters import GeminiAdapter
from agent_runtime.llm.client import LLMClient
from agent_runtime.llm.types import LLMResponse
from agent_runtime.llm import LLMRegistry, LLMProvider, ModelConfig


def _mock_gemini_response(text: str = "Hello!", usage: Optional[Dict] = None) -> bytes:
    body: Dict[str, Any] = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": text}],
                }
            }
        ],
        "usageMetadata": usage or {"promptTokenCount": 10, "candidatesTokenCount": 5},
    }
    return json.dumps(body).encode("utf-8")


def _mock_gemini_function_call_response() -> bytes:
    body: Dict[str, Any] = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "functionCall": {
                                "name": "tools.lookup",
                                "args": {"query": "status"},
                            }
                        }
                    ],
                }
            }
        ],
        "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
    }
    return json.dumps(body).encode("utf-8")


def test_gemini_adapter_call_success() -> None:
    adapter = GeminiAdapter()
    mock_resp = MagicMock()
    mock_resp.read.return_value = _mock_gemini_response("Test output")
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = adapter.call(
            api_key="gemini-test-key",
            model="gemini-2.5-flash",
            prompt="Say hello",
            system=None,
            params={},
            base_url=None,
            context=None,
        )

    assert isinstance(result, LLMResponse)
    assert result.text == "Test output"
    assert result.provider == "gemini"
    assert result.model == "gemini-2.5-flash"


def test_gemini_adapter_with_system_and_generation_config() -> None:
    adapter = GeminiAdapter()
    mock_resp = MagicMock()
    mock_resp.read.return_value = _mock_gemini_response("With system")
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        result = adapter.call(
            api_key="gemini-test-key",
            model="gemini-2.5-flash",
            prompt="Hi",
            system="You are helpful.",
            params={"temperature": 0.5, "max_tokens": 123},
            base_url=None,
            context=None,
        )

    assert result.text == "With system"
    mock_urlopen.assert_called_once()
    req = mock_urlopen.call_args[0][0]
    body = json.loads(req.data.decode("utf-8"))
    assert body["system_instruction"]["parts"][0]["text"] == "You are helpful."
    assert body["generationConfig"]["temperature"] == 0.5
    assert body["generationConfig"]["maxOutputTokens"] == 123


def test_gemini_adapter_missing_key() -> None:
    adapter = GeminiAdapter()
    with pytest.raises(ValueError, match="Missing Gemini API key"):
        adapter.call(
            api_key="",
            model="gemini-2.5-flash",
            prompt="Hi",
            system=None,
            params={},
            base_url=None,
            context=None,
        )


def test_gemini_adapter_custom_base_url() -> None:
    adapter = GeminiAdapter()
    mock_resp = MagicMock()
    mock_resp.read.return_value = _mock_gemini_response("custom")
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        adapter.call(
            api_key="gemini-test-key",
            model="gemini-2.5-flash",
            prompt="test",
            system=None,
            params={},
            base_url="https://custom.api.com/v1beta",
            context=None,
        )

    req = mock_urlopen.call_args[0][0]
    assert req.full_url == "https://custom.api.com/v1beta/models/gemini-2.5-flash:generateContent"


def test_client_routes_to_gemini() -> None:
    registry = LLMRegistry()
    provider = LLMProvider(name="gemini", api_key_env="GEMINI_API_KEY")
    provider.add_model(ModelConfig(model_id="gemini-2.5-flash"))
    registry.register_provider(provider)

    mock_adapter = MagicMock()
    mock_adapter.provider_name = "gemini"
    mock_adapter.call.return_value = LLMResponse(
        text="Routed", provider="gemini", model="gemini-2.5-flash"
    )

    client = LLMClient(
        registry=registry,
        adapters={"gemini": mock_adapter},
    )

    with patch.dict("os.environ", {"GEMINI_API_KEY": "gemini-test-key"}):
        response = client.call(model="gemini/gemini-2.5-flash", prompt="Hello")

    assert response.text == "Routed"
    mock_adapter.call.assert_called_once()


def test_gemini_adapter_native_function_call_request_and_parse() -> None:
    adapter = GeminiAdapter()
    mock_resp = MagicMock()
    mock_resp.read.return_value = _mock_gemini_function_call_response()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        result = adapter.call(
            api_key="gemini-test-key",
            model="gemini-2.5-flash",
            prompt="Check status",
            system="You are helpful.",
            params={},
            base_url=None,
            history=[
                {
                    "role": "assistant",
                    "content": "Calling lookup",
                    "_native_tool_calls": [
                        {"id": "tools.lookup", "name": "tools.lookup", "input": {"query": "health"}}
                    ],
                },
                {
                    "role": "tool_results",
                    "_native_results": [
                        {"id": "tools.lookup", "name": "tools.lookup", "content": '{"ok": true}'}
                    ],
                },
            ],
            tools=[
                {
                    "name": "tools.lookup",
                    "description": "Lookup status",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                }
            ],
            context=None,
        )

    req = mock_urlopen.call_args[0][0]
    body = json.loads(req.data.decode("utf-8"))
    assert body["tools"][0]["function_declarations"][0]["name"] == "tools.lookup"
    assert body["tool_config"]["function_calling_config"]["mode"] == "AUTO"
    # Native history should include both functionCall and functionResponse parts.
    assert any(
        content.get("role") == "model"
        and any("functionCall" in part for part in content.get("parts", []))
        for content in body["contents"]
    )
    assert any(
        content.get("role") == "user"
        and any("functionResponse" in part for part in content.get("parts", []))
        for content in body["contents"]
    )

    assert result.tool_calls
    assert result.tool_calls[0].id == "tools.lookup"
    assert result.tool_calls[0].tool_name == "tools.lookup"
    assert result.tool_calls[0].tool_input == {"query": "status"}
