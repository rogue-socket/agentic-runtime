"""Tests for the LLM handler (make_llm_handler)."""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from agent_runtime.llm.handler import make_llm_handler
from agent_runtime.llm.types import LLMResponse
from agent_runtime.state import RuntimeState


def _make_state(data: Dict[str, Any]) -> RuntimeState:
    """Build a RuntimeState with enforce_structure=False so arbitrary keys work."""
    return RuntimeState(data, enforce_structure=False)


def _mock_client(text: str = "result", provider: str = "openai", model: str = "gpt-4o") -> MagicMock:
    client = MagicMock()
    client.call.return_value = LLMResponse(
        text=text,
        provider=provider,
        model=model,
        usage={"prompt_tokens": 10, "completion_tokens": 5},
    )
    return client


class TestLLMHandler:
    """Tests for make_llm_handler()."""

    def test_basic_prompt_and_response(self) -> None:
        client = _mock_client("Hello world")
        handler = make_llm_handler(client)

        state = _make_state({
            "__llm__": {"prompt": "Say hello", "model": "gpt-4o"},
        })
        result = handler(state)

        assert result["text"] == "Hello world"
        client.call.assert_called_once()
        call_kwargs = client.call.call_args[1]
        assert call_kwargs["model"] == "gpt-4o"
        assert call_kwargs["prompt"] == "Say hello"

    def test_template_rendering(self) -> None:
        client = _mock_client("Summary done")
        handler = make_llm_handler(client)

        state = _make_state({
            "inputs": {"issue": "Bug in login"},
            "__llm__": {
                "prompt": "Summarize: {{ inputs.issue }}",
                "model": "gpt-4o",
            },
        })
        result = handler(state)

        assert result["text"] == "Summary done"
        call_kwargs = client.call.call_args[1]
        assert "Bug in login" in call_kwargs["prompt"]

    def test_system_prompt(self) -> None:
        client = _mock_client("ok")
        handler = make_llm_handler(client)

        state = _make_state({
            "__llm__": {
                "prompt": "Hello",
                "model": "gpt-4o",
                "system": "You are a code reviewer.",
            },
        })
        handler(state)

        call_kwargs = client.call.call_args[1]
        assert call_kwargs["system"] == "You are a code reviewer."

    def test_custom_response_key(self) -> None:
        client = _mock_client("answer text")
        handler = make_llm_handler(client)

        state = _make_state({
            "__llm__": {
                "prompt": "question",
                "model": "gpt-4o",
                "response_key": "answer",
            },
        })
        result = handler(state)

        assert "answer" in result
        assert result["answer"] == "answer text"
        assert "text" not in result

    def test_include_metadata(self) -> None:
        client = _mock_client("ok", provider="anthropic", model="claude-3")
        handler = make_llm_handler(client)

        state = _make_state({
            "__llm__": {
                "prompt": "hi",
                "model": "claude-3",
                "include_metadata": True,
            },
        })
        result = handler(state)

        assert "llm" in result
        assert result["llm"]["provider"] == "anthropic"
        assert result["llm"]["model"] == "claude-3"
        assert "usage" in result["llm"]

    def test_temperature_and_max_tokens(self) -> None:
        client = _mock_client("ok")
        handler = make_llm_handler(client)

        state = _make_state({
            "__llm__": {
                "prompt": "test",
                "model": "gpt-4o",
                "temperature": 0.3,
                "max_tokens": 200,
            },
        })
        handler(state)

        call_kwargs = client.call.call_args[1]
        assert call_kwargs["params"]["temperature"] == 0.3
        assert call_kwargs["params"]["max_tokens"] == 200

    def test_extra_params(self) -> None:
        client = _mock_client("ok")
        handler = make_llm_handler(client)

        state = _make_state({
            "__llm__": {
                "prompt": "test",
                "model": "gpt-4o",
                "params": {"top_p": 0.9},
            },
        })
        handler(state)

        call_kwargs = client.call.call_args[1]
        assert call_kwargs["params"]["top_p"] == 0.9

    def test_provider_forwarded(self) -> None:
        client = _mock_client("ok")
        handler = make_llm_handler(client)

        state = _make_state({
            "__llm__": {
                "prompt": "test",
                "model": "gpt-4o",
                "provider": "openai",
            },
        })
        handler(state)

        call_kwargs = client.call.call_args[1]
        assert call_kwargs["provider"] == "openai"

    def test_top_level_keys_fallback(self) -> None:
        """Keys at top level are used when __llm__ doesn't contain them."""
        client = _mock_client("fallback ok")
        handler = make_llm_handler(client)

        state = _make_state({
            "prompt": "From top level",
            "model": "gpt-4o",
        })
        result = handler(state)

        assert result["text"] == "fallback ok"
        call_kwargs = client.call.call_args[1]
        assert call_kwargs["prompt"] == "From top level"

    def test_llm_block_overrides_top_level(self) -> None:
        client = _mock_client("block ok")
        handler = make_llm_handler(client)

        state = _make_state({
            "prompt": "should be overridden",
            "model": "should-be-overridden",
            "__llm__": {
                "prompt": "From __llm__ block",
                "model": "gpt-4o-mini",
            },
        })
        result = handler(state)

        call_kwargs = client.call.call_args[1]
        assert call_kwargs["model"] == "gpt-4o-mini"
        assert call_kwargs["prompt"] == "From __llm__ block"

    def test_missing_prompt_raises(self) -> None:
        client = _mock_client()
        handler = make_llm_handler(client)

        state = _make_state({"__llm__": {"model": "gpt-4o"}})
        with pytest.raises(ValueError, match="non-empty prompt"):
            handler(state)

    def test_missing_model_raises(self) -> None:
        client = _mock_client()
        handler = make_llm_handler(client)

        state = _make_state({"__llm__": {"prompt": "hi"}})
        with pytest.raises(ValueError, match="non-empty model"):
            handler(state)

    def test_empty_prompt_raises(self) -> None:
        client = _mock_client()
        handler = make_llm_handler(client)

        state = _make_state({"__llm__": {"prompt": "   ", "model": "gpt-4o"}})
        with pytest.raises(ValueError, match="non-empty prompt"):
            handler(state)

    def test_full_state_used_for_template(self) -> None:
        client = _mock_client("ok")
        handler = make_llm_handler(client)

        state = _make_state({
            "__llm__": {
                "prompt": "Summary of {{ steps.step1.output }}",
                "model": "gpt-4o",
            },
        })
        full = {"steps": {"step1": {"output": "step result"}},
                "__llm__": {"prompt": "Summary of {{ steps.step1.output }}", "model": "gpt-4o"}}

        handler(state, full_state=full)

        call_kwargs = client.call.call_args[1]
        assert "step result" in call_kwargs["prompt"]

    def test_no_metadata_by_default(self) -> None:
        client = _mock_client("ok")
        handler = make_llm_handler(client)

        state = _make_state({"__llm__": {"prompt": "hi", "model": "gpt-4o"}})
        result = handler(state)

        assert "llm" not in result
