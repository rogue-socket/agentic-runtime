"""Tests for the OpenAI LLM adapter."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from typing import Any, Dict, Optional
from unittest.mock import patch, MagicMock, call

import pytest

from agent_runtime.llm.adapters import (
    OpenAIAdapter,
    _urlopen_with_retry,
    DEFAULT_TIMEOUT,
)
from agent_runtime.llm.client import LLMClient
from agent_runtime.llm.types import LLMResponse
from agent_runtime.llm import LLMRegistry, LLMProvider, ModelConfig


def _mock_openai_response(text: str = "Hello!", usage: Optional[Dict] = None) -> bytes:
    body: Dict[str, Any] = {
        "choices": [
            {"message": {"role": "assistant", "content": text}}
        ],
        "model": "gpt-4o",
        "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    return json.dumps(body).encode("utf-8")


def _mock_openai_tool_call_response() -> bytes:
    body: Dict[str, Any] = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "tools.lookup",
                                "arguments": '{"query": "status"}',
                            },
                        }
                    ],
                }
            }
        ],
        "model": "gpt-4o",
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    return json.dumps(body).encode("utf-8")


def _urlopen_mock(response_bytes: bytes) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.read.return_value = response_bytes
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


# --- Adapter unit tests ---


def test_openai_adapter_call_success() -> None:
    adapter = OpenAIAdapter()
    mock_resp = _urlopen_mock(_mock_openai_response("Test output"))

    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = adapter.call(
            api_key="sk-test",
            model="gpt-4o",
            prompt="Say hello",
            system=None,
            params={},
            base_url=None,
            context=None,
        )

    assert isinstance(result, LLMResponse)
    assert result.text == "Test output"
    assert result.provider == "openai"
    assert result.model == "gpt-4o"


def test_openai_adapter_with_system_prompt() -> None:
    adapter = OpenAIAdapter()
    mock_resp = _urlopen_mock(_mock_openai_response("With system"))

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        result = adapter.call(
            api_key="sk-test",
            model="gpt-4o",
            prompt="Hi",
            system="You are helpful.",
            params={"temperature": 0.7},
            base_url=None,
            context=None,
        )

    assert result.text == "With system"
    mock_urlopen.assert_called_once()
    req = mock_urlopen.call_args[0][0]
    body = json.loads(req.data.decode("utf-8"))
    assert body["messages"][0] == {"role": "system", "content": "You are helpful."}
    assert body["messages"][1] == {"role": "user", "content": "Hi"}
    assert body["temperature"] == 0.7


def test_openai_adapter_missing_key() -> None:
    adapter = OpenAIAdapter()
    with pytest.raises(ValueError, match="Missing OpenAI API key"):
        adapter.call(
            api_key="",
            model="gpt-4o",
            prompt="Hi",
            system=None,
            params={},
            base_url=None,
            context=None,
        )


def test_openai_adapter_custom_base_url() -> None:
    adapter = OpenAIAdapter()
    mock_resp = _urlopen_mock(_mock_openai_response("custom"))

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        adapter.call(
            api_key="sk-test",
            model="gpt-4o",
            prompt="test",
            system=None,
            params={},
            base_url="https://custom.api.com/v1",
            context=None,
        )

    req = mock_urlopen.call_args[0][0]
    assert req.full_url == "https://custom.api.com/v1/chat/completions"


def test_openai_adapter_no_choices_raises() -> None:
    adapter = OpenAIAdapter()
    body = json.dumps({"choices": [], "model": "gpt-4o"}).encode("utf-8")
    mock_resp = _urlopen_mock(body)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="no choices"):
            adapter.call(
                api_key="sk-test",
                model="gpt-4o",
                prompt="test",
                system=None,
                params={},
                base_url=None,
                context=None,
            )


def test_openai_adapter_empty_message_raises() -> None:
    adapter = OpenAIAdapter()
    body = json.dumps({
        "choices": [{"message": {"role": "assistant", "content": None}}],
        "model": "gpt-4o",
    }).encode("utf-8")
    mock_resp = _urlopen_mock(body)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="empty response"):
            adapter.call(
                api_key="sk-test",
                model="gpt-4o",
                prompt="test",
                system=None,
                params={},
                base_url=None,
                context=None,
            )


def test_openai_adapter_usage_returned() -> None:
    adapter = OpenAIAdapter()
    usage = {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}
    mock_resp = _urlopen_mock(_mock_openai_response("ok", usage=usage))

    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = adapter.call(
            api_key="sk-test",
            model="gpt-4o",
            prompt="test",
            system=None,
            params={},
            base_url=None,
            context=None,
        )

    assert result.usage == usage


def test_openai_adapter_params_forwarded() -> None:
    adapter = OpenAIAdapter()
    mock_resp = _urlopen_mock(_mock_openai_response("ok"))

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        adapter.call(
            api_key="sk-test",
            model="gpt-4o",
            prompt="test",
            system=None,
            params={"temperature": 0.2, "max_tokens": 100, "top_p": 0.9},
            base_url=None,
            context=None,
        )

    req = mock_urlopen.call_args[0][0]
    body = json.loads(req.data.decode("utf-8"))
    assert body["temperature"] == 0.2
    assert body["max_tokens"] == 100
    assert body["top_p"] == 0.9


def test_openai_adapter_no_system_only_user_message() -> None:
    adapter = OpenAIAdapter()
    mock_resp = _urlopen_mock(_mock_openai_response("ok"))

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        adapter.call(
            api_key="sk-test",
            model="gpt-4o",
            prompt="Just me",
            system=None,
            params={},
            base_url=None,
            context=None,
        )

    req = mock_urlopen.call_args[0][0]
    body = json.loads(req.data.decode("utf-8"))
    assert len(body["messages"]) == 1
    assert body["messages"][0]["role"] == "user"


def test_openai_adapter_native_tool_call_request_and_parse() -> None:
    adapter = OpenAIAdapter()
    mock_resp = _urlopen_mock(_mock_openai_tool_call_response())

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        result = adapter.call(
            api_key="sk-test",
            model="gpt-4o",
            prompt="Check status",
            system="You are helpful.",
            params={},
            base_url=None,
            history=[
                {
                    "role": "assistant",
                    "content": "Calling lookup",
                    "_native_tool_calls": [
                        {"id": "prev_call", "name": "tools.lookup", "input": {"query": "health"}}
                    ],
                },
                {
                    "role": "tool_results",
                    "_native_results": [
                        {"id": "prev_call", "name": "tools.lookup", "content": '{"ok": true}'}
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
    assert body["tool_choice"] == "auto"
    assert body["tools"][0]["function"]["name"] == "tools.lookup"
    # Native history should include both assistant tool_calls and tool result replay.
    assert any(m.get("role") == "assistant" and m.get("tool_calls") for m in body["messages"])
    assert any(m.get("role") == "tool" and m.get("tool_call_id") == "prev_call" for m in body["messages"])

    assert result.tool_calls
    assert result.tool_calls[0].id == "call_1"
    assert result.tool_calls[0].tool_name == "tools.lookup"
    assert result.tool_calls[0].tool_input == {"query": "status"}


# --- _urlopen_with_retry tests ---


def _make_http_error(code: int, body: str = "") -> urllib.error.HTTPError:
    import urllib.error
    exc = urllib.error.HTTPError(
        url="https://api.example.com",
        code=code,
        msg="error",
        hdrs={},  # type: ignore[arg-type]
        fp=io.BytesIO(body.encode()),
    )
    return exc


def test_retry_on_429() -> None:
    """Retryable 429 should be retried and succeed on second attempt."""
    import urllib.error

    ok_resp = _urlopen_mock(_mock_openai_response("ok"))
    err = _make_http_error(429, "rate limited")

    with patch("urllib.request.urlopen", side_effect=[err, ok_resp]) as mock_uo, \
         patch("time.sleep") as mock_sleep:
        result = _urlopen_with_retry(
            urllib.request.Request("https://api.example.com"),
            max_retries=1,
            initial_delay=0.5,
        )

    assert result["choices"][0]["message"]["content"] == "ok"
    mock_sleep.assert_called_once_with(0.5)


def test_retry_on_503() -> None:
    """Retryable 503 should be retried."""
    import urllib.error

    ok_resp = _urlopen_mock(_mock_openai_response("recovered"))
    err = _make_http_error(503, "unavailable")

    with patch("urllib.request.urlopen", side_effect=[err, ok_resp]), \
         patch("time.sleep"):
        result = _urlopen_with_retry(
            urllib.request.Request("https://api.example.com"),
            max_retries=1,
        )

    assert result["choices"][0]["message"]["content"] == "recovered"


def test_retry_exhaustion_raises() -> None:
    """When all retries are exhausted, the last HTTPError is raised."""
    import urllib.error

    err1 = _make_http_error(500, "fail1")
    err2 = _make_http_error(500, "fail2")

    with patch("urllib.request.urlopen", side_effect=[err1, err2]), \
         patch("time.sleep"):
        with pytest.raises(urllib.error.HTTPError):
            _urlopen_with_retry(
                urllib.request.Request("https://api.example.com"),
                max_retries=1,
            )


def test_no_retry_on_400() -> None:
    """Non-retryable 400 errors should not be retried."""
    import urllib.error

    err = _make_http_error(400, "bad request")

    with patch("urllib.request.urlopen", side_effect=err) as mock_uo:
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            _urlopen_with_retry(
                urllib.request.Request("https://api.example.com"),
                max_retries=2,
            )

    assert exc_info.value.code == 400
    mock_uo.assert_called_once()


def test_no_retry_on_401() -> None:
    """Auth errors (401) should not be retried."""
    import urllib.error

    err = _make_http_error(401, "unauthorized")

    with patch("urllib.request.urlopen", side_effect=err) as mock_uo:
        with pytest.raises(urllib.error.HTTPError):
            _urlopen_with_retry(
                urllib.request.Request("https://api.example.com"),
                max_retries=2,
            )

    mock_uo.assert_called_once()


def test_timeout_passed_to_urlopen() -> None:
    """The timeout parameter should be forwarded to urlopen."""
    ok_resp = _urlopen_mock(_mock_openai_response("ok"))

    with patch("urllib.request.urlopen", return_value=ok_resp) as mock_uo:
        _urlopen_with_retry(
            urllib.request.Request("https://api.example.com"),
            timeout=30,
        )

    _, kwargs = mock_uo.call_args
    assert kwargs["timeout"] == 30


def test_default_timeout() -> None:
    """Default timeout should be DEFAULT_TIMEOUT."""
    ok_resp = _urlopen_mock(_mock_openai_response("ok"))

    with patch("urllib.request.urlopen", return_value=ok_resp) as mock_uo:
        _urlopen_with_retry(urllib.request.Request("https://api.example.com"))

    _, kwargs = mock_uo.call_args
    assert kwargs["timeout"] == DEFAULT_TIMEOUT


def test_exponential_backoff_delays() -> None:
    """Retry delays should double each attempt."""
    import urllib.error

    err1 = _make_http_error(429)
    err2 = _make_http_error(429)
    ok_resp = _urlopen_mock(_mock_openai_response("ok"))

    with patch("urllib.request.urlopen", side_effect=[err1, err2, ok_resp]), \
         patch("time.sleep") as mock_sleep:
        _urlopen_with_retry(
            urllib.request.Request("https://api.example.com"),
            max_retries=2,
            initial_delay=1.0,
        )

    assert mock_sleep.call_args_list == [call(1.0), call(2.0)]


# --- LLMClient integration ---


def test_client_routes_to_openai() -> None:
    registry = LLMRegistry()
    provider = LLMProvider(name="openai", api_key_env="OPENAI_API_KEY")
    provider.add_model(ModelConfig(model_id="gpt-4o"))
    registry.register_provider(provider)

    mock_adapter = MagicMock()
    mock_adapter.provider_name = "openai"
    mock_adapter.call.return_value = LLMResponse(
        text="Routed", provider="openai", model="gpt-4o"
    )

    client = LLMClient(registry=registry, adapters={"openai": mock_adapter})

    with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
        response = client.call(model="openai/gpt-4o", prompt="Hello")

    assert response.text == "Routed"
    mock_adapter.call.assert_called_once()
