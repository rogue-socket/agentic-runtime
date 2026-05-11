"""Tests for the end-of-run summary block printed by ``ai run``."""

from __future__ import annotations

import io
import contextlib
from typing import Any, Dict

from agent_runtime.cli import _print_run_summary
from agent_runtime.models import Run, RunState, StepExecution, StepStatus


def _make_run(steps: list[StepExecution], state_data: Dict[str, Any] | None = None) -> Run:
    run = Run(
        run_id="r1",
        workflow_id="wf",
        workflow_version=None,
        workflow_hash=None,
        workflow_yaml=None,
        workflow_steps=None,
        input_hash=None,
        status=StepStatus.COMPLETED,
        created_at="2026-05-09T00:00:00",
        started_at="2026-05-09T00:00:00",
        completed_at="2026-05-09T00:00:01",
        state=RunState(state_data or {}),
    )
    for s in steps:
        run.add_step(s)
    return run


def _capture(run: Run, pricing: Dict[str, Dict[str, float]] | None = None) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        _print_run_summary(run, pricing or {})
    return buf.getvalue()


def test_summary_shows_duration() -> None:
    run = _make_run([StepExecution(step_id="a", step_type="function", status=StepStatus.COMPLETED)])
    out = _capture(run)
    assert "duration: 1000ms" in out


def test_summary_counts_completed_and_failed() -> None:
    steps = [
        StepExecution(step_id="a", step_type="function", status=StepStatus.COMPLETED),
        StepExecution(step_id="b", step_type="function", status=StepStatus.COMPLETED),
        StepExecution(step_id="c", step_type="function", status=StepStatus.FAILED),
    ]
    out = _capture(_make_run(steps))
    assert "steps: 3" in out
    assert "2 completed" in out
    assert "1 failed" in out


def test_summary_omits_tokens_when_no_llm_step() -> None:
    out = _capture(_make_run([StepExecution(step_id="a", step_type="function", status=StepStatus.COMPLETED)]))
    assert "tokens:" not in out


def test_summary_aggregates_tokens() -> None:
    steps = [
        StepExecution(
            step_id="a", step_type="agent", status=StepStatus.COMPLETED,
            token_usage={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
        ),
        StepExecution(
            step_id="b", step_type="agent", status=StepStatus.COMPLETED,
            token_usage={"input_tokens": 200, "output_tokens": 80, "total_tokens": 280},
        ),
    ]
    out = _capture(_make_run(steps))
    assert "tokens: 430" in out
    assert "input: 300" in out
    assert "output: 130" in out


def test_summary_uses_persisted_cost_when_present() -> None:
    steps = [
        StepExecution(step_id="a", step_type="agent", status=StepStatus.COMPLETED, cost_usd=0.012),
        StepExecution(step_id="b", step_type="agent", status=StepStatus.COMPLETED, cost_usd=0.003),
    ]
    out = _capture(_make_run(steps))
    assert "cost: $0.015000" in out


def test_summary_falls_back_to_recalc_when_cost_missing() -> None:
    steps = [
        StepExecution(
            step_id="a", step_type="agent", status=StepStatus.COMPLETED,
            token_usage={"input_tokens": 1000, "output_tokens": 500},
        ),
    ]
    pricing = {"*": {"input": 0.01, "output": 0.03}}
    # (1000/1000)*0.01 + (500/1000)*0.03 = 0.025
    out = _capture(_make_run(steps), pricing=pricing)
    assert "cost: $0.025000" in out


def test_summary_omits_cost_when_neither_persisted_nor_recalcable() -> None:
    out = _capture(_make_run([StepExecution(step_id="a", step_type="function", status=StepStatus.COMPLETED)]))
    assert "cost:" not in out


def test_summary_lists_output_keys() -> None:
    state = {"steps": {"classify": {"severity": "P0"}, "notify": {"posted": True}}}
    out = _capture(_make_run([], state_data=state))
    assert "outputs: classify, notify" in out


def test_summary_truncates_long_output_list() -> None:
    state = {"steps": {f"step_{i}": {"v": i} for i in range(10)}}
    out = _capture(_make_run([], state_data=state))
    assert "+4 more" in out


def test_inspect_summary_includes_tokens_and_cost(capsys) -> None:
    """Integration: ai inspect <id> (no --steps) should surface tokens + cost from persisted steps."""
    from agent_runtime.cli import run_cli
    from conftest import make_storage

    storage = make_storage()
    try:
        # Seed a minimal run + step + state_version directly via storage.
        run = Run(
            run_id="rinspect",
            workflow_id="wf",
            workflow_version=None,
            workflow_hash=None,
            workflow_yaml=None,
            workflow_steps=None,
            input_hash=None,
            status=StepStatus.COMPLETED,
            created_at="2026-05-09T00:00:00",
            started_at="2026-05-09T00:00:00",
            completed_at="2026-05-09T00:00:01",
        )
        storage.create_run(run)
        storage.append_step("rinspect", StepExecution(
            step_id="classify",
            step_type="agent",
            status=StepStatus.COMPLETED,
            execution_index=0,
            token_usage={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
            cost_usd=0.0042,
        ))
        storage.save_state("rinspect", "classify", 1, {"steps": {"classify": {"severity": "P0"}}})

        capsys.readouterr()  # clear prior buffer
        code = run_cli(["inspect", "rinspect", "--db-path", storage.db_path])
        assert code == 0
        out = capsys.readouterr().out
        assert "tokens: 150" in out
        assert "cost: $0.004200" in out
        assert "outputs: classify" in out
    finally:
        storage.close()
