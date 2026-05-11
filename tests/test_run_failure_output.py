"""Tests for inline failure-detail output emitted by ``ai run`` on FAILED runs."""

from __future__ import annotations

import io
import contextlib
from typing import Any, Dict

from agent_runtime.cli import _print_failure_details
from agent_runtime.models import Run, RunState, StepExecution, StepStatus


def _make_run(steps: list[StepExecution], run_error: str = "") -> Run:
    run = Run(
        run_id="r1",
        workflow_id="wf",
        workflow_version=None,
        workflow_hash=None,
        workflow_yaml=None,
        workflow_steps=None,
        input_hash=None,
        status=StepStatus.FAILED,
        created_at="2026-05-09T00:00:00",
        error=run_error or None,
    )
    for s in steps:
        run.add_step(s)
    return run


def _capture(run: Run) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        _print_failure_details(run)
    return buf.getvalue()


def test_surfaces_failed_step_id_and_type() -> None:
    steps = [
        StepExecution(step_id="ok1", step_type="function", status=StepStatus.COMPLETED),
        StepExecution(
            step_id="classify", step_type="function", status=StepStatus.FAILED,
            error="KeyError: 'severity'",
        ),
    ]
    out = _capture(_make_run(steps))
    assert "Failed step: classify (function)" in out
    assert "KeyError: 'severity'" in out


def test_includes_attempt_count_when_retried() -> None:
    steps = [
        StepExecution(
            step_id="flaky", step_type="tool", status=StepStatus.FAILED,
            error="ConnectionError: refused", attempt_count=3,
        ),
    ]
    out = _capture(_make_run(steps))
    assert "attempt 3" in out


def test_omits_attempt_when_first_try() -> None:
    steps = [
        StepExecution(
            step_id="x", step_type="function", status=StepStatus.FAILED,
            error="boom", attempt_count=1,
        ),
    ]
    out = _capture(_make_run(steps))
    assert "attempt" not in out


def test_falls_back_to_last_error_when_error_blank() -> None:
    steps = [
        StepExecution(
            step_id="x", step_type="agent", status=StepStatus.FAILED,
            error=None, last_error="rate limit hit",
        ),
    ]
    out = _capture(_make_run(steps))
    assert "rate limit hit" in out


def test_indents_multiline_error() -> None:
    steps = [
        StepExecution(
            step_id="x", step_type="function", status=StepStatus.FAILED,
            error="line1\nline2\nline3",
        ),
    ]
    out = _capture(_make_run(steps))
    # First line shows after `Error:`, subsequent lines are indented to align.
    assert "  Error: line1" in out
    assert "         line2" in out
    assert "         line3" in out


def test_falls_back_to_run_error_when_no_step_failed() -> None:
    """If somehow the run is FAILED but no step is marked FAILED, surface run.error."""
    out = _capture(_make_run([], run_error="workflow load failed before any step"))
    assert "workflow load failed" in out
    assert "Failed step:" not in out


def test_no_output_when_no_step_failed_and_no_run_error() -> None:
    out = _capture(_make_run([]))
    assert out == ""
