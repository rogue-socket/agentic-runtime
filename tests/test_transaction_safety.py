"""Tests for transactional persistence in SQLiteStorage and Executor.

Verifies that:
- storage.transaction() groups writes atomically
- a failure inside a transaction rolls back all writes
- nested transaction() calls are absorbed safely
- the executor persists step + state atomically per step
- the executor persists run + initial state atomically
- run initialization is consistent after creation
- backward compatibility: operations outside transaction() auto-commit
"""

from __future__ import annotations

import tempfile
from typing import Any, Dict

import pytest

from agent_runtime.core import (
    Executor,
    Run,
    StepDefinition,
    StepExecution,
    StepStatus,
)
from agent_runtime.memory.base import MemoryManager
from agent_runtime.memory.episodic import EpisodicMemory
from agent_runtime.memory.procedural import ProceduralMemory
from agent_runtime.memory.semantic import SemanticMemory
from agent_runtime.memory.working import WorkingMemory
from agent_runtime.storage.sqlite import SQLiteStorage
from agent_runtime.tools.registry import ToolRegistry


# -- helpers ------------------------------------------------------------------


def _storage() -> SQLiteStorage:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmp.close()
    return SQLiteStorage(tmp.name)


def _memory_manager() -> MemoryManager:
    return MemoryManager(
        working=WorkingMemory(),
        episodic=EpisodicMemory(),
        semantic=SemanticMemory(),
        procedural=ProceduralMemory(),
    )


def _make_step(**overrides) -> StepExecution:
    defaults = dict(
        step_id="s1",
        step_type="function",
        status=StepStatus.COMPLETED,
        started_at="2026-01-01T00:00:00Z",
        finished_at="2026-01-01T00:00:01Z",
        input={"text": "hello"},
        output={"result": "ok"},
        error=None,
        last_error=None,
        state_before={"inputs": {}, "steps": {}, "runtime": {}},
        state_after={"inputs": {}, "steps": {"s1": {"result": "ok"}}, "runtime": {}},
        duration_ms=1000,
        attempt_count=1,
        execution_index=0,
    )
    defaults.update(overrides)
    return StepExecution(**defaults)


def _make_run(storage: SQLiteStorage, run_id: str = "run-txn-test") -> Run:
    run = Run(
        run_id=run_id,
        workflow_id="test_wf",
        workflow_version="1",
        workflow_hash=None,
        workflow_yaml=None,
        workflow_steps=None,
        input_hash=None,
        status=StepStatus.RUNNING,
        created_at="2026-01-01T00:00:00Z",
        started_at="2026-01-01T00:00:00Z",
    )
    storage.create_run(run)
    return run


# -- SQLiteStorage.transaction() unit tests -----------------------------------


class TestTransactionCommit:
    """Multiple writes inside a transaction() block are committed together."""

    def test_step_and_state_committed_together(self) -> None:
        storage = _storage()
        run = _make_run(storage)

        with storage.transaction():
            storage.append_step(run.run_id, _make_step())
            storage.save_state(run.run_id, "s1", 1, {"inputs": {}, "steps": {"s1": {}}, "runtime": {}})

        steps = storage.load_steps(run.run_id)
        assert len(steps) == 1
        assert steps[0].step_id == "s1"

        state = storage.load_latest_state(run.run_id)
        assert "s1" in state["steps"]
        assert storage.load_latest_state_version(run.run_id) == 1

    def test_multiple_steps_committed_together(self) -> None:
        storage = _storage()
        run = _make_run(storage)

        with storage.transaction():
            storage.append_step(run.run_id, _make_step(step_id="s1", execution_index=0))
            storage.append_step(run.run_id, _make_step(step_id="s2", execution_index=1))
            storage.save_state(run.run_id, "s2", 1, {"done": True})

        steps = storage.load_steps(run.run_id)
        assert len(steps) == 2
        assert [s.step_id for s in steps] == ["s1", "s2"]


class TestTransactionRollback:
    """On exception, all writes in a transaction() block are rolled back."""

    def test_exception_rolls_back_all_writes(self) -> None:
        storage = _storage()
        run = _make_run(storage)

        with pytest.raises(ValueError, match="deliberate"):
            with storage.transaction():
                storage.append_step(run.run_id, _make_step(step_id="s1"))
                storage.save_state(run.run_id, "s1", 1, {"data": True})
                raise ValueError("deliberate failure")

        # Both the step and the state version must be absent.
        steps = storage.load_steps(run.run_id)
        assert len(steps) == 0

        with pytest.raises(ValueError, match="No state found"):
            storage.load_latest_state(run.run_id)

    def test_partial_writes_rolled_back(self) -> None:
        """First step succeeds, second fails — both are rolled back."""
        storage = _storage()
        run = _make_run(storage)

        with pytest.raises(RuntimeError):
            with storage.transaction():
                storage.append_step(run.run_id, _make_step(step_id="s1"))
                raise RuntimeError("crash before second write")

        steps = storage.load_steps(run.run_id)
        assert len(steps) == 0

    def test_run_status_update_rolled_back(self) -> None:
        storage = _storage()
        run = _make_run(storage)

        with pytest.raises(ValueError):
            with storage.transaction():
                storage.update_run_status(run.run_id, StepStatus.FAILED, error="boom")
                raise ValueError("rollback")

        reloaded = storage.load_run(run.run_id)
        assert reloaded.status == StepStatus.RUNNING


class TestTransactionNesting:
    """Nested transaction() calls are absorbed by the outermost transaction."""

    def test_nested_commit(self) -> None:
        storage = _storage()
        run = _make_run(storage)

        with storage.transaction():
            storage.append_step(run.run_id, _make_step(step_id="s1", execution_index=0))
            with storage.transaction():
                storage.append_step(run.run_id, _make_step(step_id="s2", execution_index=1))

        steps = storage.load_steps(run.run_id)
        assert len(steps) == 2

    def test_nested_exception_rolls_back_outer(self) -> None:
        storage = _storage()
        run = _make_run(storage)

        with pytest.raises(ValueError):
            with storage.transaction():
                storage.append_step(run.run_id, _make_step(step_id="s1", execution_index=0))
                with storage.transaction():
                    storage.append_step(run.run_id, _make_step(step_id="s2", execution_index=1))
                    raise ValueError("inner failure")

        # Both steps rolled back — inner exception propagates to outer.
        steps = storage.load_steps(run.run_id)
        assert len(steps) == 0


class TestAutoCommitOutsideTransaction:
    """Operations outside a transaction() block auto-commit individually."""

    def test_append_step_auto_commits(self) -> None:
        storage = _storage()
        run = _make_run(storage)
        storage.append_step(run.run_id, _make_step())

        steps = storage.load_steps(run.run_id)
        assert len(steps) == 1

    def test_save_state_auto_commits(self) -> None:
        storage = _storage()
        run = _make_run(storage)
        storage.save_state(run.run_id, None, 0, {"inputs": {}, "steps": {}, "runtime": {}})

        state = storage.load_latest_state(run.run_id)
        assert state == {"inputs": {}, "steps": {}, "runtime": {}}


class TestStorageClose:
    """Storage.close() releases the connection cleanly."""

    def test_close_idempotent(self) -> None:
        storage = _storage()
        storage.close()
        storage.close()  # second call should not raise

    def test_operations_after_close_raise(self) -> None:
        storage = _storage()
        storage.close()
        with pytest.raises(Exception):
            storage.load_latest_state_version("nonexistent")


# -- Executor integration tests -----------------------------------------------


def _echo_handler(inputs: Dict[str, Any]) -> Dict[str, Any]:
    return {"echo": inputs.get("text") or "default"}


def _failing_handler(inputs: Dict[str, Any]) -> Dict[str, Any]:
    raise RuntimeError("step deliberately failed")


class TestExecutorAtomicPersist:
    """Executor persists step record + state version atomically per step."""

    def test_successful_step_persists_step_and_state(self) -> None:
        storage = _storage()
        step_defs = [
            StepDefinition(
                step_id="echo",
                step_type="function",
                function_callable=_echo_handler,
                input_spec={"text": "inputs.msg"},
            ),
        ]
        executor = Executor(
            steps=step_defs,
            storage=storage,
            logger=None,
            memory_manager=_memory_manager(),
            tool_registry=ToolRegistry(),
        )

        run = executor.run(
            workflow_id="txn_test",
            initial_state={"msg": "hello"},
        )

        assert run.status == StepStatus.COMPLETED

        # Step and state must both exist.
        steps = storage.load_steps(run.run_id)
        assert len(steps) == 1
        assert steps[0].step_id == "echo"
        assert steps[0].status == StepStatus.COMPLETED

        # State version 0 (initial) + version 1 (after echo step).
        assert storage.load_latest_state_version(run.run_id) == 1
        state = storage.load_latest_state(run.run_id)
        assert state["steps"]["echo"]["echo"] == "hello"

    def test_failed_step_persists_step_and_status_atomically(self) -> None:
        storage = _storage()
        step_defs = [
            StepDefinition(
                step_id="fail",
                step_type="function",
                function_callable=_failing_handler,
            ),
        ]
        executor = Executor(
            steps=step_defs,
            storage=storage,
            logger=None,
            memory_manager=_memory_manager(),
            tool_registry=ToolRegistry(),
        )

        run = executor.run(
            workflow_id="txn_fail_test",
            initial_state={},
        )

        assert run.status == StepStatus.FAILED

        # Step record must be persisted with FAILED status.
        steps = storage.load_steps(run.run_id)
        assert len(steps) == 1
        assert steps[0].status == StepStatus.FAILED
        assert "deliberately failed" in (steps[0].error or "")

        # Run status in DB must also be FAILED.
        reloaded = storage.load_run(run.run_id)
        assert reloaded.status == StepStatus.FAILED

        # No state version beyond the initial (version 0) should be saved
        # for the failed step — the state snapshot is only saved on success.
        assert storage.load_latest_state_version(run.run_id) == 0

    def test_run_init_persists_atomically(self) -> None:
        """Run record and initial state version 0 are created atomically."""
        storage = _storage()
        step_defs = [
            StepDefinition(
                step_id="echo",
                step_type="function",
                function_callable=_echo_handler,
                input_spec={"text": "inputs.msg"},
            ),
        ]
        executor = Executor(
            steps=step_defs,
            storage=storage,
            logger=None,
            memory_manager=_memory_manager(),
            tool_registry=ToolRegistry(),
        )

        run = executor.run(workflow_id="init_test", initial_state={"msg": "hi"})

        # Run record exists with COMPLETED (ran to completion).
        reloaded = storage.load_run(run.run_id)
        assert reloaded.status == StepStatus.COMPLETED

        # Initial state (version 0) must exist.
        initial = storage.load_initial_state(run.run_id)
        assert initial["inputs"]["msg"] == "hi"

    def test_multi_step_each_step_atomic(self) -> None:
        """Each step's persist is independent — step 1 committed before step 2 runs."""
        storage = _storage()
        step_defs = [
            StepDefinition(
                step_id="s1",
                step_type="function",
                function_callable=_echo_handler,
                input_spec={"text": "inputs.msg"},
                output_contract=["echo"],
            ),
            StepDefinition(
                step_id="s2",
                step_type="function",
                function_callable=_echo_handler,
                input_spec={"text": "steps.s1.echo"},
                output_contract=["echo"],
            ),
        ]
        executor = Executor(
            steps=step_defs,
            storage=storage,
            logger=None,
            memory_manager=_memory_manager(),
            tool_registry=ToolRegistry(),
        )

        run = executor.run(workflow_id="multi", initial_state={"msg": "chain"})
        assert run.status == StepStatus.COMPLETED

        steps = storage.load_steps(run.run_id)
        assert len(steps) == 2
        assert steps[0].step_id == "s1"
        assert steps[1].step_id == "s2"

        # State version 0 (init) + 1 (after s1) + 2 (after s2).
        assert storage.load_latest_state_version(run.run_id) == 2

        final = storage.load_latest_state(run.run_id)
        assert final["steps"]["s1"]["echo"] == "chain"
        assert final["steps"]["s2"]["echo"] == "chain"


class TestTransactionStateProperty:
    """Verify the _in_transaction flag behaves correctly."""

    def test_not_in_transaction_initially(self) -> None:
        storage = _storage()
        assert storage._in_transaction is False

    def test_in_transaction_inside_block(self) -> None:
        storage = _storage()
        with storage.transaction():
            assert storage._in_transaction is True
        assert storage._in_transaction is False

    def test_in_transaction_reset_after_exception(self) -> None:
        storage = _storage()
        with pytest.raises(RuntimeError):
            with storage.transaction():
                assert storage._in_transaction is True
                raise RuntimeError("boom")
        assert storage._in_transaction is False
