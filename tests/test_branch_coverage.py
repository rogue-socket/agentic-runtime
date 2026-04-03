"""Tests for branch coverage tracking via RunReplayer.branch_coverage()."""

from __future__ import annotations

import os
import copy

import pytest

from agent_runtime.core import Run, RunState, StepExecution, StepStatus
from agent_runtime.replay import RunReplayer, BranchCoverageReport
from agent_runtime.storage.sqlite import SQLiteStorage
from agent_runtime.utils import utc_now


def _make_storage(tmp_path: str) -> SQLiteStorage:
    """Function implementation."""
    return SQLiteStorage(os.path.join(tmp_path, "test.db"))


def _seed_run(storage: SQLiteStorage, run_id: str, steps: list[StepExecution]) -> None:
    """Function implementation."""
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


# Workflow with one branching step that has two targets.
WORKFLOW_STEPS = [
    {
        "step_id": "classify",
        "next_rules": [
            {"goto": "escalate", "when": "state.steps.classify.severity == 'P0'"},
            {"goto": "close", "when": "state.steps.classify.severity == 'P2'"},
        ],
    },
    {"step_id": "escalate"},
    {"step_id": "close"},
]


class TestBranchCoverage:
    def test_full_coverage(self, tmp_path):
        """Function implementation."""
        storage = _make_storage(str(tmp_path))
        # Run 1 takes the escalate branch
        step1 = StepExecution(
            step_id="classify", step_type="agent", status=StepStatus.COMPLETED,
            next_step_resolved="escalate", execution_index=0,
        )
        _seed_run(storage, "run-1", [step1])

        # Run 2 takes the close branch
        step2 = StepExecution(
            step_id="classify", step_type="agent", status=StepStatus.COMPLETED,
            next_step_resolved="close", execution_index=0,
        )
        _seed_run(storage, "run-2", [step2])

        replayer = RunReplayer(storage, printer=lambda _: None)
        result = replayer.branch_coverage(WORKFLOW_STEPS, ["run-1", "run-2"])
        assert isinstance(result, BranchCoverageReport)
        assert result.total_branches == 2
        assert result.covered_branches == 2
        assert result.coverage_pct == 100.0
        assert result.untested == []

    def test_partial_coverage(self, tmp_path):
        """Function implementation."""
        storage = _make_storage(str(tmp_path))
        step = StepExecution(
            step_id="classify", step_type="agent", status=StepStatus.COMPLETED,
            next_step_resolved="escalate", execution_index=0,
        )
        _seed_run(storage, "run-1", [step])

        replayer = RunReplayer(storage, printer=lambda _: None)
        result = replayer.branch_coverage(WORKFLOW_STEPS, ["run-1"])
        assert result.total_branches == 2
        assert result.covered_branches == 1
        assert result.coverage_pct == 50.0
        assert len(result.untested) == 1
        assert result.untested[0]["step_id"] == "classify"
        assert result.untested[0]["target"] == "close"

    def test_zero_coverage(self, tmp_path):
        """Function implementation."""
        storage = _make_storage(str(tmp_path))
        replayer = RunReplayer(storage, printer=lambda _: None)
        result = replayer.branch_coverage(WORKFLOW_STEPS, [])
        assert result.total_branches == 2
        assert result.covered_branches == 0
        assert result.coverage_pct == 0.0
        assert len(result.untested) == 2

    def test_no_branches_100_pct(self, tmp_path):
        """Workflow with no branching steps reports 100% coverage."""
        storage = _make_storage(str(tmp_path))
        replayer = RunReplayer(storage, printer=lambda _: None)
        result = replayer.branch_coverage(
            [{"step_id": "s1"}, {"step_id": "s2"}], []
        )
        assert result.total_branches == 0
        assert result.coverage_pct == 100.0

    def test_next_step_resolved_persisted(self, tmp_path):
        """next_step_resolved survives SQLite roundtrip."""
        storage = _make_storage(str(tmp_path))
        step = StepExecution(
            step_id="classify", step_type="agent", status=StepStatus.COMPLETED,
            next_step_resolved="escalate", execution_index=0,
        )
        _seed_run(storage, "run-x", [step])
        loaded = storage.load_steps("run-x")
        assert loaded[0].next_step_resolved == "escalate"

    def test_invalid_run_ids_skipped(self, tmp_path):
        """Non-existent run IDs don't crash, just skip."""
        storage = _make_storage(str(tmp_path))
        replayer = RunReplayer(storage, printer=lambda _: None)
        result = replayer.branch_coverage(WORKFLOW_STEPS, ["nonexistent-run"])
        assert result.covered_branches == 0
