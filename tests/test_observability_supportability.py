from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
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
    """Function implementation."""
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
    """Function implementation."""
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


def test_serialize_agent_trace_redacts_sensitive_patterns() -> None:
    """Function implementation."""
    turns = [
        _FakeTurn(
            iteration=1,
            llm_request={
                "prompt": "email me at user@example.com and use sk-1234567890ABCDEFGHIJ",
                "authorization": "Bearer abcdefghijklmnop",
            },
            llm_response=_FakeResponse(
                text="token=supersecret123",
                model="openai/gpt-4o",
                usage={"total_tokens": 10},
            ),
            tool_calls=[],
        )
    ]

    events = serialize_agent_trace(turns)
    assert events[0]["type"] == "model"
    prompt = events[0]["llm_request"]["prompt"]
    assert "user@example.com" not in prompt
    assert "sk-1234567890ABCDEFGHIJ" not in prompt
    assert "[REDACTED_EMAIL]" in prompt
    assert "[REDACTED_API_KEY]" in prompt
    assert "[REDACTED]" in events[0]["llm_request"]["authorization"]
    assert "supersecret123" not in events[0]["response_text"]


def test_error_taxonomy_helpers_return_stable_code_and_message() -> None:
    """Function implementation."""
    exc = StepExecutionError("step failed")
    assert get_error_code(exc) == "AR-STEP-EXECUTION"
    message = get_user_message(exc)
    assert message != str(exc)
    assert "workflow step" in message.lower()


def test_storage_observability_report_aggregates_run_and_step_stats() -> None:
    """Function implementation."""
    storage = make_storage()
    tools = ToolRegistry()

    def ok(inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Function implementation."""
        return {"ok": True}

    def boom(inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Function implementation."""
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


def test_storage_observability_report_includes_health_and_diagnostics_layers() -> None:
    """Function implementation."""
    storage = make_storage()
    tools = ToolRegistry()

    workflow_yaml = """
schema_version: v1
workflow:
  id: wf_diag
  version: v1
steps:
  - id: classify
    type: function
  - id: act
    type: function
"""

    def classify(inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Function implementation."""
        return {"confidence": 0.92}

    def act(inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Function implementation."""
        mode = (inputs.get("inputs") or {}).get("mode")
        if mode == "fail":
            raise ValueError("ActionError: simulated")
        return {"ok": True, "confidence": 0.61}

    executor = Executor(
        [
            StepDefinition(step_id="classify", step_type="function", function_callable=classify),
            StepDefinition(step_id="act", step_type="function", function_callable=act),
        ],
        storage,
        None,
        make_memory_manager(),
        tools,
    )

    run_prev = executor.run("wf_diag", {"mode": "ok"}, workflow_yaml=workflow_yaml)
    run_fail = executor.run("wf_diag", {"mode": "fail"}, workflow_yaml=workflow_yaml)
    run_curr = executor.run("wf_diag", {"mode": "ok"}, workflow_yaml=workflow_yaml)

    assert run_prev.status == StepStatus.COMPLETED
    assert run_fail.status == StepStatus.FAILED
    assert run_curr.status == StepStatus.COMPLETED

    now = datetime.now(timezone.utc)

    storage._conn_execute(
        "UPDATE runs SET created_at = ?, started_at = ?, completed_at = ?, metadata_json = ? WHERE id = ?",
        (
            (now - timedelta(days=9)).isoformat(),
            (now - timedelta(days=9, minutes=1)).isoformat(),
            (now - timedelta(days=9, minutes=1)).isoformat(),
            json.dumps(
                {
                    "outcome_achieved": True,
                    "oracle_passed": True,
                    "oracle_scenario_id": "oracle-prev",
                    "input_class": "legacy",
                    "confidence": 0.88,
                }
            ),
            run_prev.run_id,
        ),
    )
    storage._conn_execute(
        "UPDATE runs SET created_at = ?, started_at = ?, completed_at = ?, metadata_json = ? WHERE id = ?",
        (
            (now - timedelta(days=1)).isoformat(),
            (now - timedelta(days=1, minutes=1)).isoformat(),
            (now - timedelta(days=1, minutes=1)).isoformat(),
            json.dumps(
                {
                    "human_touched": True,
                    "input_class": "novel",
                    "confidence": 0.95,
                }
            ),
            run_fail.run_id,
        ),
    )
    storage._conn_execute(
        "UPDATE runs SET created_at = ?, started_at = ?, completed_at = ?, metadata_json = ? WHERE id = ?",
        (
            now.isoformat(),
            (now - timedelta(seconds=4)).isoformat(),
            now.isoformat(),
            json.dumps(
                {
                    "outcome_achieved": True,
                    "oracle_passed": False,
                    "oracle_scenario_id": "oracle-curr",
                    "input_class": "legacy",
                    "confidence": 0.60,
                }
            ),
            run_curr.run_id,
        ),
    )

    report = storage.build_observability_report(top_steps=5, window_days=7, latency_target_ms=2000)

    assert "health" in report
    assert "diagnostics" in report
    assert "outcomes" in report

    current_outcomes = report["outcomes"]["current"]
    assert current_outcomes["ads_rate"] is not None
    assert current_outcomes["human_touch_rate"] is not None
    assert current_outcomes["recovery_efficiency"] is not None

    current_attribution = report["diagnostics"]["step_attribution"]["current"]
    assert current_attribution["first_break_step_rate"]
    assert current_attribution["first_break_step_rate"][0]["step_id"] == "act"

    input_coverage = report["diagnostics"]["input_coverage"]
    assert input_coverage["current_novel_input_share"] is not None
    assert input_coverage["current_novel_input_share"] > 0

    calibration = report["diagnostics"]["calibration"]["current"]
    assert calibration["samples"] >= 1
    assert calibration["ece"] is not None

    health = report["health"]
    assert health["current"]["score"] is not None
    assert health["status"] in {"improving", "mixed", "regressing", "insufficient_baseline"}


def test_normalize_token_usage_handles_provider_shapes() -> None:
    """OpenAI/Anthropic/Gemini usage dicts all resolve to (input, output, total)."""
    from agent_runtime.models import normalize_token_usage

    openai = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
    assert normalize_token_usage(openai) == (10, 20, 30)

    anthropic = {"input_tokens": 12, "output_tokens": 8}
    assert normalize_token_usage(anthropic) == (12, 8, 20)

    gemini = {"promptTokenCount": 5, "candidatesTokenCount": 7, "totalTokenCount": 12}
    assert normalize_token_usage(gemini) == (5, 7, 12)

    assert normalize_token_usage(None) == (0, 0, 0)
    assert normalize_token_usage({}) == (0, 0, 0)


def test_observability_report_counts_gemini_shape_tokens() -> None:
    """Regression for #8: build_observability_report must count camelCase Gemini keys."""
    storage = make_storage()
    tools = ToolRegistry()

    def stub(inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Function implementation."""
        return {"ok": True}

    executor = Executor(
        [StepDefinition(step_id="s", step_type="function", function_callable=stub)],
        storage,
        None,
        make_memory_manager(),
        tools,
    )
    run = executor.run("wf_gemini", {"x": 1})
    assert run.status == StepStatus.COMPLETED

    # Backfill a step row with a Gemini-shape usage payload so the aggregator must
    # normalize camelCase keys to count it.
    with storage._lock:  # type: ignore[attr-defined]
        cur = storage._conn.cursor()  # type: ignore[attr-defined]
        cur.execute(
            "UPDATE steps SET token_usage_json = ? WHERE run_id = ?",
            (json.dumps({"promptTokenCount": 11, "candidatesTokenCount": 22, "totalTokenCount": 33}), run.run_id),
        )
        storage._conn.commit()  # type: ignore[attr-defined]

    report = storage.build_observability_report(top_steps=5)
    assert report["llm"]["total_tokens"] >= 33
