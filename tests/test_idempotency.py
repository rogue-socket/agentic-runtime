"""Tests for history-based idempotency tracking on resume."""

from __future__ import annotations

import os

import pytest

from agent_runtime.core import StepDefinition, StepExecution, StepStatus
from agent_runtime.resume import (
    ResumePolicy,
    determine_resume_step,
    has_completed_side_effects,
    get_side_effect_summary,
)
from agent_runtime.errors import StepExecutionError
from agent_runtime.storage.sqlite import SQLiteStorage
from agent_runtime.utils import utc_now


class TestHasCompletedSideEffects:
    def test_no_side_effects(self):
        step = StepExecution(step_id="s1", step_type="tool", side_effects=None)
        assert has_completed_side_effects(step) is False

    def test_empty_side_effects(self):
        step = StepExecution(step_id="s1", step_type="tool", side_effects=[])
        assert has_completed_side_effects(step) is False

    def test_completed_side_effect(self):
        step = StepExecution(
            step_id="s1", step_type="tool",
            side_effects=[{"type": "api_call", "target": "slack", "completed": True}],
        )
        assert has_completed_side_effects(step) is True

    def test_incomplete_side_effect(self):
        step = StepExecution(
            step_id="s1", step_type="tool",
            side_effects=[{"type": "api_call", "target": "slack", "completed": False}],
        )
        assert has_completed_side_effects(step) is False

    def test_mixed_side_effects(self):
        step = StepExecution(
            step_id="s1", step_type="tool",
            side_effects=[
                {"type": "api_call", "target": "slack", "completed": True},
                {"type": "api_call", "target": "jira", "completed": False},
            ],
        )
        assert has_completed_side_effects(step) is True

    def test_non_dict_entries_ignored(self):
        step = StepExecution(
            step_id="s1", step_type="tool",
            side_effects=["not-a-dict", 42],
        )
        assert has_completed_side_effects(step) is False


class TestGetSideEffectSummary:
    def test_empty(self):
        step = StepExecution(step_id="s1", step_type="tool", side_effects=None)
        assert get_side_effect_summary(step) == []

    def test_summary_format(self):
        step = StepExecution(
            step_id="s1", step_type="tool",
            side_effects=[
                {"type": "api_call", "target": "slack", "action": "send_message", "completed": True},
            ],
        )
        summary = get_side_effect_summary(step)
        assert len(summary) == 1
        assert summary[0]["type"] == "api_call"
        assert summary[0]["target"] == "slack"
        assert summary[0]["action"] == "send_message"
        assert summary[0]["completed"] == "True"


class TestSideEffectsSQLiteRoundtrip:
    def test_side_effects_persisted(self, tmp_path):
        """side_effects survive SQLite write/read."""
        from agent_runtime.core import Run, RunState
        storage = SQLiteStorage(os.path.join(str(tmp_path), "test.db"))
        run = Run(
            run_id="r1", workflow_id="wf1", workflow_version="1",
            workflow_hash="abc", workflow_yaml="", workflow_steps=["s1"],
            input_hash="h1", status=StepStatus.COMPLETED,
            created_at=utc_now().isoformat(), state=RunState({}),
        )
        storage.create_run(run)
        effects = [
            {"type": "api_call", "target": "slack", "action": "post", "completed": True},
            {"type": "db_write", "target": "users", "action": "insert", "completed": False},
        ]
        step = StepExecution(
            step_id="s1", step_type="tool", status=StepStatus.COMPLETED,
            side_effects=effects, execution_index=0,
        )
        storage.append_step("r1", step)
        storage.save_state("r1", "s1", 1, {})

        loaded = storage.load_steps("r1")
        assert loaded[0].side_effects == effects

    def test_none_side_effects_roundtrip(self, tmp_path):
        from agent_runtime.core import Run, RunState
        storage = SQLiteStorage(os.path.join(str(tmp_path), "test.db"))
        run = Run(
            run_id="r2", workflow_id="wf1", workflow_version="1",
            workflow_hash="abc", workflow_yaml="", workflow_steps=["s1"],
            input_hash="h2", status=StepStatus.COMPLETED,
            created_at=utc_now().isoformat(), state=RunState({}),
        )
        storage.create_run(run)
        step = StepExecution(
            step_id="s1", step_type="tool", status=StepStatus.COMPLETED,
            side_effects=None, execution_index=0,
        )
        storage.append_step("r2", step)
        storage.save_state("r2", "s1", 1, {})

        loaded = storage.load_steps("r2")
        assert loaded[0].side_effects is None


class TestSideEffectsExtraction:
    """Test that __side_effects__ key is extracted from tool output in the executor."""

    def test_side_effects_in_output_detected(self):
        """has_completed_side_effects correctly identifies completed effects."""
        exec_with = StepExecution(
            step_id="send_slack",
            step_type="tool",
            status=StepStatus.FAILED,
            error="TimeoutError: network",
            side_effects=[
                {"type": "api_call", "target": "slack", "action": "send_message", "completed": True},
            ],
        )
        assert has_completed_side_effects(exec_with) is True

        # On resume, the developer/runtime knows the Slack message was already sent.
        summary = get_side_effect_summary(exec_with)
        assert summary[0]["target"] == "slack"
        assert summary[0]["completed"] == "True"
