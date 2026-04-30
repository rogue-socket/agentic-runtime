"""Tests for the typed event system."""

from __future__ import annotations

from agent_runtime.events import (
    RunCompleteEvent,
    RunStartEvent,
    StepCompleteEvent,
    StepErrorEvent,
    StepStartEvent,
    _parse_event,
    adapt_typed_callback,
)


class TestParseEvent:
    def test_run_start(self):
        event = _parse_event("RUN_START", {"run_id": "r1", "workflow_id": "w1"})
        assert isinstance(event, RunStartEvent)
        assert event.run_id == "r1"
        assert event.workflow_id == "w1"

    def test_step_start(self):
        event = _parse_event("STEP_START", {
            "run_id": "r1", "step_id": "s1", "step_type": "tool", "execution_index": 0,
        })
        assert isinstance(event, StepStartEvent)
        assert event.step_id == "s1"

    def test_step_complete(self):
        event = _parse_event("STEP_COMPLETE", {
            "run_id": "r1", "step_id": "s1", "step_type": "tool",
            "duration_ms": 42, "attempt_count": 1, "tool_duration_ms": 30,
        })
        assert isinstance(event, StepCompleteEvent)
        assert event.duration_ms == 42
        assert event.tool_duration_ms == 30

    def test_step_error(self):
        event = _parse_event("STEP_ERROR", {
            "run_id": "r1", "step_id": "s1", "step_type": "tool",
            "error": "boom", "attempt_count": 3,
        })
        assert isinstance(event, StepErrorEvent)
        assert event.error == "boom"

    def test_run_complete(self):
        event = _parse_event("RUN_COMPLETE", {"run_id": "r1", "status": "COMPLETED"})
        assert isinstance(event, RunCompleteEvent)
        assert event.status == "COMPLETED"
        assert event.error is None

    def test_unknown_event_returns_none(self):
        assert _parse_event("STEP_HEARTBEAT", {"run_id": "r1"}) is None

    def test_extra_payload_fields_are_ignored(self):
        event = _parse_event("RUN_START", {
            "run_id": "r1", "workflow_id": "w1", "extra_field": "ignored",
        })
        assert isinstance(event, RunStartEvent)
        assert not hasattr(event, "extra_field")


class TestAdaptTypedCallback:
    def test_receives_typed_events(self):
        received = []
        raw_cb = adapt_typed_callback(lambda e: received.append(e))

        raw_cb("RUN_START", {"run_id": "r1", "workflow_id": "w1"})
        raw_cb("STEP_HEARTBEAT", {"run_id": "r1"})  # no typed counterpart
        raw_cb("RUN_COMPLETE", {"run_id": "r1", "status": "COMPLETED"})

        assert len(received) == 2
        assert isinstance(received[0], RunStartEvent)
        assert isinstance(received[1], RunCompleteEvent)
