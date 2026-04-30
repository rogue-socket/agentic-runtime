"""Tests for Run dataclass accessor methods."""

from __future__ import annotations

from agent_runtime.core import Run, RunState, StepExecution, StepStatus


def _make_run(**overrides) -> Run:
    """Create a minimal Run with sensible defaults."""
    defaults = dict(
        run_id="r1",
        workflow_id="w1",
        workflow_version="v1",
        workflow_hash=None,
        workflow_yaml=None,
        workflow_steps=None,
        input_hash=None,
        status=StepStatus.COMPLETED,
        created_at="2026-01-01T00:00:00+00:00",
        started_at="2026-01-01T00:00:00+00:00",
        completed_at="2026-01-01T00:00:01+00:00",
        state=RunState({"inputs": {"topic": "AI"}, "steps": {"research": {"findings": "good"}}}),
    )
    defaults.update(overrides)
    return Run(**defaults)


class TestGetOutput:
    def test_returns_step_output(self):
        run = _make_run()
        assert run.get_output("research") == {"findings": "good"}

    def test_returns_none_for_missing_step(self):
        run = _make_run()
        assert run.get_output("nonexistent") is None


class TestGetInput:
    def test_returns_input_value(self):
        run = _make_run()
        assert run.get_input("topic") == "AI"

    def test_returns_default_for_missing_key(self):
        run = _make_run()
        assert run.get_input("missing") is None
        assert run.get_input("missing", "fallback") == "fallback"


class TestStatusProperties:
    def test_succeeded_when_completed(self):
        run = _make_run(status=StepStatus.COMPLETED)
        assert run.succeeded is True
        assert run.failed is False

    def test_failed_when_failed(self):
        run = _make_run(status=StepStatus.FAILED)
        assert run.succeeded is False
        assert run.failed is True

    def test_neither_when_running(self):
        run = _make_run(status=StepStatus.RUNNING)
        assert run.succeeded is False
        assert run.failed is False


class TestOutputs:
    def test_returns_all_step_outputs(self):
        state = RunState({"steps": {"a": {"x": 1}, "b": {"y": 2}}})
        run = _make_run(state=state)
        assert run.outputs == {"a": {"x": 1}, "b": {"y": 2}}

    def test_returns_empty_when_no_steps(self):
        run = _make_run(state=RunState({}))
        assert run.outputs == {}


class TestStepNames:
    def test_returns_ordered_step_ids(self):
        run = _make_run()
        run._steps = [
            StepExecution(step_id="a", step_type="tool"),
            StepExecution(step_id="b", step_type="function"),
        ]
        assert run.step_names == ["a", "b"]

    def test_empty_when_no_steps(self):
        run = _make_run()
        assert run.step_names == []


class TestTotalDurationMs:
    def test_computes_from_timestamps(self):
        run = _make_run(
            started_at="2026-01-01T00:00:00+00:00",
            completed_at="2026-01-01T00:00:02+00:00",
        )
        assert run.total_duration_ms == 2000

    def test_none_when_not_completed(self):
        run = _make_run(started_at="2026-01-01T00:00:00+00:00", completed_at=None)
        assert run.total_duration_ms is None


class TestTotalTokens:
    def test_sums_across_steps(self):
        run = _make_run()
        run._steps = [
            StepExecution(step_id="a", step_type="agent", token_usage={"total_tokens": 100}),
            StepExecution(step_id="b", step_type="agent", token_usage={"total_tokens": 200}),
        ]
        assert run.total_tokens == 300

    def test_zero_when_no_usage(self):
        run = _make_run()
        run._steps = [
            StepExecution(step_id="a", step_type="tool", token_usage=None),
        ]
        assert run.total_tokens == 0

    def test_zero_when_no_steps(self):
        run = _make_run()
        assert run.total_tokens == 0
