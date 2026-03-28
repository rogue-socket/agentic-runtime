from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from agent_runtime.core import Executor, StepDefinition, StepStatus
from agent_runtime.errors import StepExecutionError, get_error_code, get_user_message
from agent_runtime.observability import normalize_agent_trace, serialize_agent_trace
from agent_runtime.tools.registry import ToolRegistry
from conftest import make_memory_manager, make_storage


@dataclass
class _FakeResponse:
    text: str
    model: str
    usage: Dict[str, Any]


@dataclass
class _FakeToolResult:
    success: bool
    output: Dict[str, Any]
    error: str | None = None


@dataclass
class _FakeToolCall:
    tool_name: str
    tool_input: Dict[str, Any]
    result: _FakeToolResult
    duration_ms: int = 0


@dataclass
class _FakeTurn:
    iteration: int
    llm_request: Dict[str, Any]
    llm_response: _FakeResponse
    tool_calls: list[_FakeToolCall]


def test_serialize_agent_trace_produces_model_and_tool_events() -> None:
    turns = [
        _FakeTurn(
            iteration=1,
            llm_request={"prompt": "review"},
            llm_response=_FakeResponse(
                text="done",
                model="openai/gpt-4o",
                usage={"total_tokens": 42},
            ),
            tool_calls=[
                _FakeToolCall(
                    tool_name="tools.echo",
                    tool_input={"message": "hi"},
                    result=_FakeToolResult(success=True, output={"ok": True}),
                    duration_ms=7,
                )
            ],
        )
    ]

    events = serialize_agent_trace(turns)
    assert len(events) == 2
    assert events[0]["type"] == "model"
    assert events[0]["model"] == "openai/gpt-4o"
    assert events[1]["type"] == "tool"
    assert events[1]["tool"] == "tools.echo"


def test_normalize_agent_trace_handles_legacy_shape() -> None:
    legacy = [
        {
            "iteration": 1,
            "llm_request": {"prompt": "review"},
            "llm_response_text": "looks good",
            "tool_calls": [
                {
                    "tool": "tools.echo",
                    "input": {"message": "ok"},
                    "success": True,
                    "duration_ms": 9,
                }
            ],
        }
    ]

    normalized = normalize_agent_trace(legacy)
    assert len(normalized) == 2
    assert normalized[0]["type"] == "model"
    assert normalized[0]["response_text"] == "looks good"
    assert normalized[1]["type"] == "tool"
    assert normalized[1]["tool"] == "tools.echo"


def test_error_taxonomy_helpers_return_stable_code_and_message() -> None:
    exc = StepExecutionError("step failed")
    assert get_error_code(exc) == "AR-STEP-EXECUTION"
    message = get_user_message(exc)
    assert message != str(exc)
    assert "workflow step" in message.lower()


def test_storage_observability_report_aggregates_run_and_step_stats() -> None:
    storage = make_storage()
    tools = ToolRegistry()

    def ok(inputs: Dict[str, Any]) -> Dict[str, Any]:
        return {"ok": True}

    def boom(inputs: Dict[str, Any]) -> Dict[str, Any]:
        raise ValueError("boom")

    ok_executor = Executor(
        [StepDefinition(step_id="ok_step", step_type="function", function_callable=ok)],
        storage,
        None,
        make_memory_manager(),
        tools,
    )
    fail_executor = Executor(
        [StepDefinition(step_id="fail_step", step_type="function", function_callable=boom)],
        storage,
        None,
        make_memory_manager(),
        tools,
    )

    run_ok = ok_executor.run("wf_ok", {"x": 1})
    run_fail = fail_executor.run("wf_fail", {"x": 1})

    assert run_ok.status == StepStatus.COMPLETED
    assert run_fail.status == StepStatus.FAILED

    report = storage.build_observability_report(top_steps=5)
    assert report["runs"]["total"] >= 2
    assert report["runs"]["failed"] >= 1
    assert report["steps"]["total"] >= 2
    assert report["errors"]["top_classes"]
