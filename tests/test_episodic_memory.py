"""Tests for SQLite-backed episodic memory."""

from __future__ import annotations

import os
import tempfile

from agent_runtime.memory.episodic import EpisodicMemory


class TestEpisodicMemoryStubMode:
    """Backward-compatible stub mode (no db_path)."""

    def test_read_returns_empty_initially(self) -> None:
        """Function implementation."""
        mem = EpisodicMemory()
        assert mem.read({}) == {}

    def test_write_and_read_stub(self) -> None:
        """Function implementation."""
        mem = EpisodicMemory()
        mem.write({"key": "value"})
        result = mem.read({})
        assert result == {"key": "value"}

    def test_recall_returns_empty_in_stub(self) -> None:
        """Function implementation."""
        mem = EpisodicMemory()
        assert mem.recall("any_workflow") == []


class TestEpisodicMemorySQLite:
    """SQLite-backed mode."""

    def _db(self, tmpdir: str) -> str:
        """Function implementation."""
        return os.path.join(tmpdir, "test_memory.db")

    def test_record_and_recall(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = EpisodicMemory(db_path=self._db(tmpdir))
            try:
                mem.record(
                    workflow_id="wf1",
                    run_id="run-001",
                    status="COMPLETED",
                    inputs_summary="issue",
                    outputs_summary="summary, severity",
                )
                mem.record(
                    workflow_id="wf1",
                    run_id="run-002",
                    status="FAILED",
                    inputs_summary="issue",
                    error="StepExecutionError: timeout",
                )

                episodes = mem.recall("wf1")
                assert len(episodes) == 2
                # Most recent first
                assert episodes[0]["run_id"] == "run-002"
                assert episodes[0]["status"] == "FAILED"
                assert episodes[0]["error"] == "StepExecutionError: timeout"
                assert episodes[1]["run_id"] == "run-001"
                assert episodes[1]["status"] == "COMPLETED"
            finally:
                mem.close()

    def test_recall_filters_by_workflow_id(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = EpisodicMemory(db_path=self._db(tmpdir))
            try:
                mem.record(workflow_id="wf1", run_id="r1", status="COMPLETED")
                mem.record(workflow_id="wf2", run_id="r2", status="COMPLETED")

                wf1 = mem.recall("wf1")
                assert len(wf1) == 1
                assert wf1[0]["workflow_id"] == "wf1"
            finally:
                mem.close()

    def test_recall_limit(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = EpisodicMemory(db_path=self._db(tmpdir))
            try:
                for i in range(10):
                    mem.record(workflow_id="wf1", run_id=f"r{i}", status="COMPLETED")

                episodes = mem.recall("wf1", limit=3)
                assert len(episodes) == 3
            finally:
                mem.close()

    def test_recall_all(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = EpisodicMemory(db_path=self._db(tmpdir))
            try:
                mem.record(workflow_id="wf1", run_id="r1", status="COMPLETED")
                mem.record(workflow_id="wf2", run_id="r2", status="FAILED")

                all_episodes = mem.recall_all(limit=10)
                assert len(all_episodes) == 2
            finally:
                mem.close()

    def test_write_persists_episode(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = EpisodicMemory(db_path=self._db(tmpdir))
            try:
                mem.write({
                    "inputs": {"issue": "bug report"},
                    "steps": {"summarize": {"summary": "..."}, "classify": {"severity": "high"}},
                    "runtime": {
                        "workflow_id": "triage",
                        "run_id": "run-xyz",
                        "status": "COMPLETED",
                    },
                })

                episodes = mem.recall("triage")
                assert len(episodes) == 1
                ep = episodes[0]
                assert ep["workflow_id"] == "triage"
                assert ep["run_id"] == "run-xyz"
                assert ep["status"] == "COMPLETED"
                assert "issue" in ep["inputs_summary"]
                assert "summarize" in ep["outputs_summary"]
            finally:
                mem.close()

    def test_read_hydrates_runtime_episodes(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = EpisodicMemory(db_path=self._db(tmpdir))
            try:
                mem.record(workflow_id="wf1", run_id="r1", status="COMPLETED")

                context = {"runtime": {"workflow_id": "wf1"}}
                result = mem.read(context)
                assert "episodes" in result
                assert len(result["episodes"]) == 1
            finally:
                mem.close()

    def test_read_returns_empty_for_unknown_workflow(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = EpisodicMemory(db_path=self._db(tmpdir))
            try:
                result = mem.read({"runtime": {"workflow_id": "nonexistent"}})
                assert result == {}
            finally:
                mem.close()

    def test_persistence_across_instances(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db = self._db(tmpdir)
            mem1 = EpisodicMemory(db_path=db)
            mem1.record(workflow_id="wf1", run_id="r1", status="COMPLETED")
            mem1.close()

            # New instance, same DB
            mem2 = EpisodicMemory(db_path=db)
            try:
                episodes = mem2.recall("wf1")
                assert len(episodes) == 1
                assert episodes[0]["run_id"] == "r1"
            finally:
                mem2.close()

    def test_max_recall_config(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = EpisodicMemory(db_path=self._db(tmpdir), max_recall=2)
            try:
                for i in range(5):
                    mem.record(workflow_id="wf1", run_id=f"r{i}", status="COMPLETED")

                # read() respects max_recall
                context = {"runtime": {"workflow_id": "wf1"}}
                result = mem.read(context)
                assert len(result["episodes"]) == 2
            finally:
                mem.close()
