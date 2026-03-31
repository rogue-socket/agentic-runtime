"""Tests for model regression detection via compare_runs()."""

from __future__ import annotations

import copy
import tempfile
import os

import pytest

from agent_runtime.core import Run, RunState, StepExecution, StepStatus
from agent_runtime.replay import RunReplayer, RunComparison, StepDiff
from agent_runtime.storage.sqlite import SQLiteStorage
from agent_runtime.utils import utc_now


def _make_storage(tmp_path: str) -> SQLiteStorage:
    return SQLiteStorage(os.path.join(tmp_path, "test.db"))


def _seed_run(storage: SQLiteStorage, run_id: str, steps: list[StepExecution]) -> None:
    """Create a run with given steps."""
    run = Run(
        run_id=run_id,
        workflow_id="wf1",
        workflow_version="1",
        workflow_hash="abc",
        workflow_yaml="steps: []",
        workflow_steps=["s1"],
        input_hash="h1",
        status=StepStatus.COMPLETED,
        created_at=utc_now().isoformat(),
        state=RunState({}),
    )
    storage.create_run(run)
    for step in steps:
        storage.append_step(run_id, step)
    storage.save_state(run_id, None, 0, {})


class TestCompareRuns:
    def test_identical_runs_no_diffs(self, tmp_path):
        storage = _make_storage(str(tmp_path))
        step = StepExecution(
            step_id="s1", step_type="agent", status=StepStatus.COMPLETED,
            output={"summary": "hello"}, model_name="gpt-4o-2024-05-13",
            execution_index=0,
        )
        _seed_run(storage, "run-a", [copy.deepcopy(step)])
        _seed_run(storage, "run-b", [copy.deepcopy(step)])

        replayer = RunReplayer(storage, printer=lambda _: None)
        result = replayer.compare_runs("run-a", "run-b")
        assert isinstance(result, RunComparison)
        assert result.steps_compared == 1
        assert not result.has_diffs
        assert result.diffs == []

    def test_model_name_diff_detected(self, tmp_path):
        storage = _make_storage(str(tmp_path))
        step_a = StepExecution(
            step_id="s1", step_type="agent", status=StepStatus.COMPLETED,
            output={"summary": "same"}, model_name="gpt-4o-2024-05-13",
            execution_index=0,
        )
        step_b = StepExecution(
            step_id="s1", step_type="agent", status=StepStatus.COMPLETED,
            output={"summary": "same"}, model_name="gpt-4o-2024-08-06",
            execution_index=0,
        )
        _seed_run(storage, "run-a", [step_a])
        _seed_run(storage, "run-b", [step_b])

        replayer = RunReplayer(storage, printer=lambda _: None)
        result = replayer.compare_runs("run-a", "run-b")
        assert result.has_diffs
        model_diffs = [d for d in result.diffs if d.field == "model_name"]
        assert len(model_diffs) == 1
        assert model_diffs[0].value_a == "gpt-4o-2024-05-13"
        assert model_diffs[0].value_b == "gpt-4o-2024-08-06"

    def test_output_diff_detected(self, tmp_path):
        storage = _make_storage(str(tmp_path))
        step_a = StepExecution(
            step_id="s1", step_type="function", status=StepStatus.COMPLETED,
            output={"result": "A"}, execution_index=0,
        )
        step_b = StepExecution(
            step_id="s1", step_type="function", status=StepStatus.COMPLETED,
            output={"result": "B"}, execution_index=0,
        )
        _seed_run(storage, "run-a", [step_a])
        _seed_run(storage, "run-b", [step_b])

        replayer = RunReplayer(storage, printer=lambda _: None)
        result = replayer.compare_runs("run-a", "run-b")
        assert result.has_diffs
        output_diffs = [d for d in result.diffs if d.field == "output"]
        assert len(output_diffs) == 1

    def test_missing_step_detected(self, tmp_path):
        storage = _make_storage(str(tmp_path))
        step_a = StepExecution(
            step_id="s1", step_type="function", status=StepStatus.COMPLETED,
            output={"x": 1}, execution_index=0,
        )
        step_b1 = StepExecution(
            step_id="s1", step_type="function", status=StepStatus.COMPLETED,
            output={"x": 1}, execution_index=0,
        )
        step_b2 = StepExecution(
            step_id="s2", step_type="function", status=StepStatus.COMPLETED,
            output={"y": 2}, execution_index=1,
        )
        _seed_run(storage, "run-a", [step_a])
        _seed_run(storage, "run-b", [step_b1, step_b2])

        replayer = RunReplayer(storage, printer=lambda _: None)
        result = replayer.compare_runs("run-a", "run-b")
        assert result.has_diffs
        presence_diffs = [d for d in result.diffs if d.field == "presence"]
        assert len(presence_diffs) == 1
        assert presence_diffs[0].step_id == "s2"
        assert presence_diffs[0].value_a == "missing"

    def test_status_diff_detected(self, tmp_path):
        storage = _make_storage(str(tmp_path))
        step_a = StepExecution(
            step_id="s1", step_type="agent", status=StepStatus.COMPLETED,
            output={"r": 1}, execution_index=0,
        )
        step_b = StepExecution(
            step_id="s1", step_type="agent", status=StepStatus.FAILED,
            error="timeout", execution_index=0,
        )
        _seed_run(storage, "run-a", [step_a])
        _seed_run(storage, "run-b", [step_b])

        replayer = RunReplayer(storage, printer=lambda _: None)
        result = replayer.compare_runs("run-a", "run-b")
        status_diffs = [d for d in result.diffs if d.field == "status"]
        assert len(status_diffs) == 1

    def test_model_name_persisted_roundtrip(self, tmp_path):
        """model_name survives SQLite write/read."""
        storage = _make_storage(str(tmp_path))
        step = StepExecution(
            step_id="s1", step_type="agent", status=StepStatus.COMPLETED,
            model_name="claude-3.5-sonnet", execution_index=0,
        )
        _seed_run(storage, "run-x", [step])
        loaded = storage.load_steps("run-x")
        assert loaded[0].model_name == "claude-3.5-sonnet"
