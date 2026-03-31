"""Tests for Tier 2 fixes: config overlay, latency budget, golden snapshot testing."""

from __future__ import annotations

import asyncio
import copy
import json
import os
import tempfile
import time

import pytest

from agent_runtime.config import (
    RuntimeConfig,
    load_config,
    _interpolate_env_vars,
    _deep_merge,
)
from agent_runtime.core import (
    Executor,
    Run,
    StepDefinition,
    StepExecution,
    StepStatus,
)
from agent_runtime.errors import (
    ReplayDataMissingError,
    ReplayMismatchError,
    StepExecutionError,
    WorkflowValidationError,
)
from agent_runtime.logging import StructuredLogger
from agent_runtime.memory.base import MemoryManager
from agent_runtime.memory.working import WorkingMemory
from agent_runtime.memory.episodic import EpisodicMemory
from agent_runtime.memory.semantic import SemanticMemory
from agent_runtime.memory.procedural import ProceduralMemory
from agent_runtime.replay import GoldenFixture, ReplayResult, RunReplayer
from agent_runtime.storage.sqlite import SQLiteStorage
from agent_runtime.tools.registry import ToolRegistry
from agent_runtime.workflow import _parse_workflow


def _with_schema(body: str) -> str:
    return "schema_version: v1\n" + body


def _make_memory_manager():
    return MemoryManager(
        working=WorkingMemory(),
        episodic=EpisodicMemory(),
        semantic=SemanticMemory(),
        procedural=ProceduralMemory(),
    )


# ---------------------------------------------------------------------------
# Fix 1: Config env-var interpolation + environment overlay
# ---------------------------------------------------------------------------


class TestInterpolateEnvVars:

    def test_simple_substitution(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_DB", "prod.db")
        assert _interpolate_env_vars("${MY_DB}") == "prod.db"

    def test_unset_var_left_as_is(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NONEXISTENT_VAR_XYZ", raising=False)
        assert _interpolate_env_vars("${NONEXISTENT_VAR_XYZ}") == "${NONEXISTENT_VAR_XYZ}"

    def test_nested_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOST", "localhost")
        result = _interpolate_env_vars({"server": {"host": "${HOST}", "port": 8080}})
        assert result == {"server": {"host": "localhost", "port": 8080}}

    def test_list_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ITEM", "foo")
        result = _interpolate_env_vars(["${ITEM}", "bar"])
        assert result == ["foo", "bar"]

    def test_non_string_passthrough(self) -> None:
        assert _interpolate_env_vars(42) == 42
        assert _interpolate_env_vars(None) is None

    def test_mixed_text_and_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PREFIX", "prod")
        assert _interpolate_env_vars("db_${PREFIX}.sqlite") == "db_prod.sqlite"


class TestDeepMerge:

    def test_flat_overlay(self) -> None:
        base = {"a": 1, "b": 2}
        overlay = {"b": 3, "c": 4}
        assert _deep_merge(base, overlay) == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self) -> None:
        base = {"llm": {"model": "gpt-4o", "temp": 0.2}}
        overlay = {"llm": {"temp": 0.0}}
        assert _deep_merge(base, overlay) == {"llm": {"model": "gpt-4o", "temp": 0.0}}

    def test_overlay_adds_nested_key(self) -> None:
        base = {"llm": {"model": "gpt-4o"}}
        overlay = {"llm": {"timeout": 30}}
        assert _deep_merge(base, overlay) == {"llm": {"model": "gpt-4o", "timeout": 30}}


class TestConfigOverlayFile:

    def test_overlay_loaded_when_runtime_env_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with tempfile.TemporaryDirectory() as d:
            base_path = os.path.join(d, "runtime.yaml")
            overlay_path = os.path.join(d, "runtime.prod.yaml")
            with open(base_path, "w") as f:
                f.write(_with_schema("db_path: dev.db\noverwrite_policy: warn\n"))
            with open(overlay_path, "w") as f:
                f.write("db_path: prod.db\noverwrite_policy: strict\n")
            monkeypatch.setenv("RUNTIME_ENV", "prod")
            cfg = load_config(base_path)
            assert cfg.db_path == "prod.db"
            assert cfg.overwrite_policy == "strict"

    def test_no_overlay_when_env_not_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("RUNTIME_ENV", raising=False)
        with tempfile.TemporaryDirectory() as d:
            base_path = os.path.join(d, "runtime.yaml")
            with open(base_path, "w") as f:
                f.write(_with_schema("db_path: dev.db\n"))
            cfg = load_config(base_path)
            assert cfg.db_path == "dev.db"

    def test_env_var_interpolation_in_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CUSTOM_DB", "/data/prod.db")
        monkeypatch.delenv("RUNTIME_ENV", raising=False)
        with tempfile.TemporaryDirectory() as d:
            base_path = os.path.join(d, "runtime.yaml")
            with open(base_path, "w") as f:
                f.write(_with_schema("db_path: ${CUSTOM_DB}\n"))
            cfg = load_config(base_path)
            assert cfg.db_path == "/data/prod.db"

    def test_overlay_missing_file_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RUNTIME_ENV", "staging")
        with tempfile.TemporaryDirectory() as d:
            base_path = os.path.join(d, "runtime.yaml")
            with open(base_path, "w") as f:
                f.write(_with_schema("db_path: dev.db\n"))
            cfg = load_config(base_path)
            assert cfg.db_path == "dev.db"


# ---------------------------------------------------------------------------
# Fix 2: Workflow-level latency budget
# ---------------------------------------------------------------------------


def _make_slow_step(delay_s: float):
    """Create a function callable that sleeps for *delay_s* seconds."""
    def slow_func(state):
        time.sleep(delay_s)
        return {"done": True}
    return slow_func


def _make_executor(steps, latency_budget_ms=None, db_path=":memory:"):
    storage = SQLiteStorage(db_path)
    return Executor(
        steps=steps,
        storage=storage,
        logger=StructuredLogger(),
        memory_manager=_make_memory_manager(),
        tool_registry=ToolRegistry(),
        latency_budget_ms=latency_budget_ms,
    ), storage


class TestLatencyBudgetParsing:

    def test_valid_budget_parsed(self) -> None:
        yaml_text = (
            "schema_version: v1\n"
            "workflow:\n  id: w\n  version: v1\n"
            "latency_budget_ms: 5000\n"
            "steps:\n  - id: a\n    type: tool\n    tool: tools.echo\n"
        )
        wf = _parse_workflow(yaml_text)
        assert wf["latency_budget_ms"] == 5000

    def test_no_budget_is_none(self) -> None:
        yaml_text = (
            "schema_version: v1\n"
            "workflow:\n  id: w\n  version: v1\n"
            "steps:\n  - id: a\n    type: tool\n    tool: tools.echo\n"
        )
        wf = _parse_workflow(yaml_text)
        assert wf["latency_budget_ms"] is None

    def test_invalid_budget_rejected(self) -> None:
        yaml_text = (
            "schema_version: v1\n"
            "workflow:\n  id: w\n  version: v1\n"
            "latency_budget_ms: -100\n"
            "steps:\n  - id: a\n    type: tool\n    tool: tools.echo\n"
        )
        with pytest.raises(WorkflowValidationError, match="latency_budget_ms"):
            _parse_workflow(yaml_text)

    def test_string_budget_rejected(self) -> None:
        yaml_text = (
            "schema_version: v1\n"
            "workflow:\n  id: w\n  version: v1\n"
            "latency_budget_ms: fast\n"
            "steps:\n  - id: a\n    type: tool\n    tool: tools.echo\n"
        )
        with pytest.raises(WorkflowValidationError, match="latency_budget_ms"):
            _parse_workflow(yaml_text)


class TestLatencyBudgetEnforcement:

    def test_budget_exceeded_raises(self) -> None:
        """Two steps each sleeping 60ms with a 50ms budget should fail."""
        steps = [
            StepDefinition(
                step_id="s1", step_type="function",
                function_callable=_make_slow_step(0.06),
            ),
            StepDefinition(
                step_id="s2", step_type="function",
                function_callable=_make_slow_step(0.06),
            ),
        ]
        executor, storage = _make_executor(steps, latency_budget_ms=50)
        with pytest.raises(StepExecutionError, match="latency budget exceeded"):
            executor.run(
                workflow_id="w",
                initial_state={"key": "val"},
                workflow_version="v1",
            )
        storage.close()

    def test_within_budget_succeeds(self) -> None:
        """A fast step within a generous budget should complete normally."""
        steps = [
            StepDefinition(
                step_id="fast", step_type="function",
                function_callable=lambda state: {"ok": True},
            ),
        ]
        executor, storage = _make_executor(steps, latency_budget_ms=10000)
        run = executor.run(
            workflow_id="w",
            initial_state={"key": "val"},
            workflow_version="v1",
        )
        assert run.status == StepStatus.COMPLETED
        storage.close()

    def test_no_budget_no_enforcement(self) -> None:
        """Without a budget, slow steps complete normally."""
        steps = [
            StepDefinition(
                step_id="slow", step_type="function",
                function_callable=_make_slow_step(0.05),
            ),
        ]
        executor, storage = _make_executor(steps, latency_budget_ms=None)
        run = executor.run(
            workflow_id="w",
            initial_state={"key": "val"},
            workflow_version="v1",
        )
        assert run.status == StepStatus.COMPLETED
        storage.close()


# ---------------------------------------------------------------------------
# Fix 3: Golden snapshot testing
# ---------------------------------------------------------------------------


def _setup_completed_run(storage: SQLiteStorage):
    """Create a minimal completed run in storage and return (run_id, initial_state)."""
    from agent_runtime.core import Run, RunState
    from agent_runtime.utils import utc_now

    run_id = "golden-test-run"
    initial_state = {"inputs": {"query": "hello"}, "steps": {}, "runtime": {"workflow_id": "w", "run_id": run_id}}

    run = Run(
        run_id=run_id,
        workflow_id="w",
        workflow_version="v1",
        workflow_hash="abc123",
        workflow_yaml="steps: []",
        workflow_steps=["s1"],
        input_hash="inp",
        status=StepStatus.COMPLETED,
        created_at=utc_now().isoformat(),
        started_at=utc_now().isoformat(),
        completed_at=utc_now().isoformat(),
        state=RunState(_data=copy.deepcopy(initial_state)),
    )
    storage.create_run(run)
    storage.save_state(run_id, None, 0, initial_state)

    state_after = copy.deepcopy(initial_state)
    state_after["steps"]["s1"] = {"answer": "world"}

    step = StepExecution(
        step_id="s1",
        step_type="function",
        status=StepStatus.COMPLETED,
        state_before=copy.deepcopy(initial_state),
        state_after=state_after,
        output={"answer": "world"},
        execution_index=1,
    )
    storage.append_step(run_id, step)
    storage.save_state(run_id, "s1", 1, state_after)

    return run_id, initial_state


class TestGoldenCapture:

    def test_capture_returns_fixture(self) -> None:
        storage = SQLiteStorage(":memory:")
        run_id, initial_state = _setup_completed_run(storage)
        replayer = RunReplayer(storage, printer=lambda _: None)
        fixture = replayer.capture_golden(run_id)
        assert isinstance(fixture, GoldenFixture)
        assert fixture.run_id == run_id
        assert fixture.workflow_id == "w"
        assert fixture.initial_state == initial_state
        assert len(fixture.steps) == 1
        assert fixture.steps[0]["step_id"] == "s1"
        assert fixture.steps[0]["output"] == {"answer": "world"}
        storage.close()

    def test_capture_rejects_failed_run(self) -> None:
        storage = SQLiteStorage(":memory:")
        from agent_runtime.core import Run, RunState
        from agent_runtime.utils import utc_now
        run = Run(
            run_id="fail-run", workflow_id="w", workflow_version="v1",
            workflow_hash="h", workflow_yaml="", workflow_steps=[],
            input_hash="i", status=StepStatus.FAILED,
            created_at=utc_now().isoformat(),
            state=RunState(_data={"inputs": {}, "steps": {}, "runtime": {}}),
        )
        storage.create_run(run)
        replayer = RunReplayer(storage, printer=lambda _: None)
        with pytest.raises(ReplayDataMissingError, match="COMPLETED"):
            replayer.capture_golden("fail-run")
        storage.close()


class TestGoldenSaveLoad:

    def test_round_trip(self) -> None:
        fixture = GoldenFixture(
            run_id="r1",
            workflow_id="w1",
            initial_state={"inputs": {"x": 1}, "steps": {}, "runtime": {}},
            steps=[{"step_id": "s1", "state_before": {}, "state_after": {"y": 2}, "output": {"y": 2}}],
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            path = f.name
        try:
            RunReplayer.save_golden(fixture, path)
            loaded = RunReplayer.load_golden(path)
            assert loaded.run_id == fixture.run_id
            assert loaded.workflow_id == fixture.workflow_id
            assert loaded.initial_state == fixture.initial_state
            assert loaded.steps == fixture.steps
        finally:
            os.unlink(path)


class TestGoldenReplay:

    def test_consistent_fixture_passes(self) -> None:
        state_0 = {"inputs": {"q": "hi"}, "steps": {}, "runtime": {}}
        state_1 = {"inputs": {"q": "hi"}, "steps": {"s1": {"a": 1}}, "runtime": {}}
        fixture = GoldenFixture(
            run_id="r1",
            workflow_id="w1",
            initial_state=state_0,
            steps=[{
                "step_id": "s1",
                "step_type": "function",
                "status": "COMPLETED",
                "state_before": state_0,
                "state_after": state_1,
                "output": {"a": 1},
            }],
        )
        result = RunReplayer.replay_golden(fixture)
        assert result.steps_replayed == 1
        assert result.final_state == state_1

    def test_inconsistent_fixture_raises(self) -> None:
        state_0 = {"inputs": {"q": "hi"}, "steps": {}, "runtime": {}}
        wrong_before = {"inputs": {"q": "WRONG"}, "steps": {}, "runtime": {}}
        fixture = GoldenFixture(
            run_id="r1",
            workflow_id="w1",
            initial_state=state_0,
            steps=[{
                "step_id": "s1",
                "step_type": "function",
                "status": "COMPLETED",
                "state_before": wrong_before,
                "state_after": {"done": True},
                "output": {},
            }],
        )
        with pytest.raises(ReplayMismatchError, match="Golden state mismatch"):
            RunReplayer.replay_golden(fixture)

    def test_multi_step_golden(self) -> None:
        s0 = {"inputs": {}, "steps": {}, "runtime": {}}
        s1 = {"inputs": {}, "steps": {"a": {"x": 1}}, "runtime": {}}
        s2 = {"inputs": {}, "steps": {"a": {"x": 1}, "b": {"y": 2}}, "runtime": {}}
        fixture = GoldenFixture(
            run_id="r1", workflow_id="w1",
            initial_state=s0,
            steps=[
                {"step_id": "a", "state_before": s0, "state_after": s1, "output": {"x": 1}},
                {"step_id": "b", "state_before": s1, "state_after": s2, "output": {"y": 2}},
            ],
        )
        result = RunReplayer.replay_golden(fixture)
        assert result.steps_replayed == 2
        assert result.final_state == s2
