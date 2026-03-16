"""Tests for SQLiteStorage roundtrip correctness.

Verifies that empty dicts are persisted and loaded correctly, not silently
converted to NULL (the truthiness bug fixed in append_step).
"""

from __future__ import annotations

import tempfile

from agent_runtime.core import StepExecution, StepStatus
from agent_runtime.storage.sqlite import SQLiteStorage


def _storage() -> SQLiteStorage:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmp.close()
    return SQLiteStorage(tmp.name)


def _make_step(**overrides) -> StepExecution:
    defaults = dict(
        step_id="s1",
        step_type="model",
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
        step = _make_step(input={})
        storage.append_step("run1", step)

        loaded = storage.load_steps("run1")
        assert len(loaded) == 1
        assert loaded[0].input == {}

    def test_empty_output_roundtrips(self) -> None:
        storage = _storage()
        step = _make_step(output={})
        storage.append_step("run1", step)

        loaded = storage.load_steps("run1")
        assert loaded[0].output == {}

    def test_empty_state_before_roundtrips(self) -> None:
        storage = _storage()
        step = _make_step(state_before={})
        storage.append_step("run1", step)

        loaded = storage.load_steps("run1")
        assert loaded[0].state_before == {}

    def test_empty_state_after_roundtrips(self) -> None:
        storage = _storage()
        step = _make_step(state_after={})
        storage.append_step("run1", step)

        loaded = storage.load_steps("run1")
        assert loaded[0].state_after == {}

    def test_none_stays_none(self) -> None:
        storage = _storage()
        step = _make_step(input=None, output=None, state_before=None, state_after=None)
        storage.append_step("run1", step)

        loaded = storage.load_steps("run1")
        assert loaded[0].input is None
        assert loaded[0].output is None
        assert loaded[0].state_before is None
        assert loaded[0].state_after is None

    def test_populated_dict_roundtrips(self) -> None:
        storage = _storage()
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
