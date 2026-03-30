"""Regression tests for the mock LLM adapter native tool-calling flow."""

from __future__ import annotations

from unittest.mock import patch

from agent_runtime.llm.adapters import MockAdapter


def _sample_tools() -> list[dict]:
    return [
        {
            "name": "tools.lookup",
            "description": "Lookup status",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        }
    ]


def test_mock_adapter_emits_valid_tool_call_request() -> None:
    adapter = MockAdapter()

    with patch("agent_runtime.llm.adapters.time.sleep", return_value=None):
        response = adapter.call(
            api_key="mock-key",
            model="mock-model",
            prompt="Check status",
            system=None,
            params={},
            base_url=None,
            tools=_sample_tools(),
            history=[],
            context=None,
        )

    assert response.tool_calls
    assert response.tool_calls[0].tool_name == "tools.lookup"
    assert response.tool_calls[0].tool_input == {
        "query": "mock search",
        "input": "mock data",
    }


def test_mock_adapter_stops_after_native_tool_results_history() -> None:
    adapter = MockAdapter()

    history = [
        {
            "role": "assistant",
            "content": "Calling lookup",
            "_native_tool_calls": [
                {"id": "call_1", "name": "tools.lookup", "input": {"query": "status"}}
            ],
        },
        {
            "role": "tool_results",
            "_native_results": [
                {"id": "call_1", "name": "tools.lookup", "content": '{"ok": true}'}
            ],
        },
    ]

    with patch("agent_runtime.llm.adapters.time.sleep", return_value=None):
        response = adapter.call(
            api_key="mock-key",
            model="mock-model",
            prompt="Check status",
            system=None,
            params={},
            base_url=None,
            tools=_sample_tools(),
            history=history,
            context=None,
        )

    assert response.tool_calls == []
    assert "final_answer" in response.text


def test_mock_adapter_stops_after_text_observation_history() -> None:
    adapter = MockAdapter()

    history = [
        {
            "role": "assistant",
            "content": "I will call tools.lookup",
        },
        {
            "role": "user",
            "content": "Tool observation:\nTool tools.lookup result: {\"ok\": true}",
        },
    ]

    with patch("agent_runtime.llm.adapters.time.sleep", return_value=None):
        response = adapter.call(
            api_key="mock-key",
            model="mock-model",
            prompt="Check status",
            system=None,
            params={},
            base_url=None,
            tools=_sample_tools(),
            history=history,
            context=None,
        )

    assert response.tool_calls == []
    assert "final_answer" in response.text
