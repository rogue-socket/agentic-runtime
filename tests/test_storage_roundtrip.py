"""Tests for SQLiteStorage roundtrip correctness.

Verifies that empty dicts are persisted and loaded correctly, not silently
converted to NULL (the truthiness bug fixed in append_step).
"""

from __future__ import annotations

import tempfile

from agent_runtime.core import Run, StepExecution, StepStatus
from agent_runtime.storage.sqlite import SQLiteStorage


def _storage() -> SQLiteStorage:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmp.close()
    return SQLiteStorage(tmp.name)


def _ensure_run(storage: SQLiteStorage, run_id: str = "run1") -> None:
    """Create a minimal run record so FK constraints are satisfied."""
    run = Run(
        run_id=run_id,
        workflow_id="wf",
        workflow_version=None,
        workflow_hash=None,
        workflow_yaml=None,
        workflow_steps=None,
        input_hash=None,
        status=StepStatus.RUNNING,
        created_at="2026-01-01T00:00:00Z",
    )
    storage.create_run(run)


def _make_step(**overrides) -> StepExecution:
    defaults = dict(
        step_id="s1",
        step_type="function",
        status=StepStatus.COMPLETED,
        started_at="2026-01-01T00:00:00Z",
        finished_at="2026-01-01T00:00:01Z",
        input=None,
        output=None,
        error=None,
        last_error=None,
        state_before=None,
        state_after=None,
        duration_ms=1000,
        attempt_count=1,
        execution_index=0,
    )
    defaults.update(overrides)
    return StepExecution(**defaults)


class TestAppendStepEmptyDict:
    """Empty dicts ({}) must survive the write→read roundtrip as dicts, not None."""

    def test_empty_input_roundtrips(self) -> None:
        storage = _storage()
        _ensure_run(storage)
        step = _make_step(input={})
        storage.append_step("run1", step)

        loaded = storage.load_steps("run1")
        assert len(loaded) == 1
        assert loaded[0].input == {}

    def test_empty_output_roundtrips(self) -> None:
        storage = _storage()
        _ensure_run(storage)
        step = _make_step(output={})
        storage.append_step("run1", step)

        loaded = storage.load_steps("run1")
        assert loaded[0].output == {}

    def test_empty_state_before_roundtrips(self) -> None:
        storage = _storage()
        _ensure_run(storage)
        step = _make_step(state_before={})
        storage.append_step("run1", step)

        loaded = storage.load_steps("run1")
        assert loaded[0].state_before == {}

    def test_empty_state_after_roundtrips(self) -> None:
        storage = _storage()
        _ensure_run(storage)
        step = _make_step(state_after={})
        storage.append_step("run1", step)

        loaded = storage.load_steps("run1")
        assert loaded[0].state_after == {}

    def test_none_stays_none(self) -> None:
        storage = _storage()
        _ensure_run(storage)
        step = _make_step(input=None, output=None, state_before=None, state_after=None)
        storage.append_step("run1", step)

        loaded = storage.load_steps("run1")
        assert loaded[0].input is None
        assert loaded[0].output is None
        assert loaded[0].state_before is None
        assert loaded[0].state_after is None

    def test_populated_dict_roundtrips(self) -> None:
        storage = _storage()
        _ensure_run(storage)
        step = _make_step(
            input={"issue": "test"},
            output={"summary": "done"},
            state_before={"inputs": {"issue": "test"}, "steps": {}, "runtime": {}},
            state_after={"inputs": {"issue": "test"}, "steps": {"s1": {"summary": "done"}}, "runtime": {}},
        )
        storage.append_step("run1", step)

        loaded = storage.load_steps("run1")
        assert loaded[0].input == {"issue": "test"}
        assert loaded[0].output == {"summary": "done"}
        assert loaded[0].state_before["inputs"]["issue"] == "test"
        assert loaded[0].state_after["steps"]["s1"]["summary"] == "done"


class TestAgentTraceRoundtrip:
    """Verify agent_trace field survives write→read roundtrip (C1 fix)."""

    def test_agent_trace_none_stays_none(self) -> None:
        storage = _storage()
        _ensure_run(storage)
        step = _make_step(agent_trace=None)
        storage.append_step("run1", step)

        loaded = storage.load_steps("run1")
        assert loaded[0].agent_trace is None

    def test_agent_trace_roundtrips(self) -> None:
        storage = _storage()
        _ensure_run(storage)
        trace = [
            {
                "iteration": 1,
                "llm_request": "Summarize this issue",
                "llm_response_text": "The issue is about login failures.",
                "tool_calls": [
                    {"tool": "tools.echo", "input": {"message": "hi"},
                     "success": True, "duration_ms": 5}
                ],
                "observation": "Tool returned successfully",
            },
            {
                "iteration": 2,
                "llm_request": "Any more details?",
                "llm_response_text": "No further info needed.",
                "tool_calls": [],
                "observation": None,
            },
        ]
        step = _make_step(agent_trace=trace)
        storage.append_step("run1", step)

        loaded = storage.load_steps("run1")
        assert loaded[0].agent_trace is not None
        assert len(loaded[0].agent_trace) == 2
        assert loaded[0].agent_trace[0]["iteration"] == 1
        assert loaded[0].agent_trace[0]["tool_calls"][0]["tool"] == "tools.echo"
        assert loaded[0].agent_trace[1]["llm_response_text"] == "No further info needed."

    def test_empty_trace_list_roundtrips(self) -> None:
        storage = _storage()
        _ensure_run(storage)
        step = _make_step(agent_trace=[])
        storage.append_step("run1", step)

        loaded = storage.load_steps("run1")
        assert loaded[0].agent_trace == []
