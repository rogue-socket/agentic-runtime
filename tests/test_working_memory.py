"""Tests for WorkingMemory — scratch store, sliding window, active task."""

from __future__ import annotations

import pytest

from agent_runtime.memory.working import WorkingMemory


class TestScratchStore:

    def test_put_and_get(self) -> None:
        """Function implementation."""
        wm = WorkingMemory()
        wm.put("plan", "fix the bug")
        assert wm.get("plan") == "fix the bug"

    def test_get_missing_returns_default(self) -> None:
        """Function implementation."""
        wm = WorkingMemory()
        assert wm.get("nope") is None
        assert wm.get("nope", "fallback") == "fallback"

    def test_remove(self) -> None:
        """Function implementation."""
        wm = WorkingMemory()
        wm.put("key", "value")
        wm.remove("key")
        assert wm.get("key") is None

    def test_remove_missing_no_error(self) -> None:
        """Function implementation."""
        wm = WorkingMemory()
        wm.remove("nonexistent")  # should not raise

    def test_clear_scratch(self) -> None:
        """Function implementation."""
        wm = WorkingMemory()
        wm.put("a", 1)
        wm.put("b", 2)
        wm.clear_scratch()
        assert wm.get("a") is None
        assert wm.get("b") is None

    def test_byte_budget_enforcement(self) -> None:
        """Function implementation."""
        wm = WorkingMemory(max_scratch_bytes=50)
        wm.put("small", "ok")
        with pytest.raises(ValueError, match="byte budget exceeded"):
            wm.put("big", "x" * 200)

    def test_byte_budget_allows_after_removal(self) -> None:
        """Function implementation."""
        wm = WorkingMemory(max_scratch_bytes=100)
        wm.put("fill", "x" * 50)
        wm.remove("fill")
        wm.put("new", "y" * 50)  # should succeed now
        assert wm.get("new") == "y" * 50


class TestSlidingWindow:

    def test_add_and_recent_entries(self) -> None:
        """Function implementation."""
        wm = WorkingMemory()
        wm.add_entry("observation", {"text": "first"})
        wm.add_entry("observation", {"text": "second"})
        entries = wm.recent_entries()
        assert len(entries) == 2
        assert entries[0]["text"] == "first"
        assert entries[1]["text"] == "second"

    def test_recent_entries_limit(self) -> None:
        """Function implementation."""
        wm = WorkingMemory()
        for i in range(5):
            wm.add_entry("step_output", {"i": i})
        entries = wm.recent_entries(limit=2)
        assert len(entries) == 2
        assert entries[0]["i"] == 3
        assert entries[1]["i"] == 4

    def test_eviction_at_max_entries(self) -> None:
        """Function implementation."""
        wm = WorkingMemory(max_entries=3)
        for i in range(5):
            wm.add_entry("event", {"i": i})
        entries = wm.recent_entries()
        assert len(entries) == 3
        # oldest two (i=0, i=1) evicted
        assert entries[0]["i"] == 2

    def test_entries_include_kind(self) -> None:
        """Function implementation."""
        wm = WorkingMemory()
        wm.add_entry("tool_call", {"tool": "echo"})
        entries = wm.recent_entries()
        assert entries[0]["kind"] == "tool_call"

    def test_entries_are_deep_copied(self) -> None:
        """Function implementation."""
        wm = WorkingMemory()
        wm.add_entry("obs", {"data": [1, 2, 3]})
        entries = wm.recent_entries()
        entries[0]["data"].append(99)
        # Original should be unchanged
        assert 99 not in wm.recent_entries()[0]["data"]


class TestActiveTask:

    def test_set_and_get_active_task(self) -> None:
        """Function implementation."""
        wm = WorkingMemory()
        wm.set_active_task({"goal": "fix login"})
        task = wm.get_active_task()
        assert task == {"goal": "fix login"}

    def test_no_active_task_returns_none(self) -> None:
        """Function implementation."""
        wm = WorkingMemory()
        assert wm.get_active_task() is None

    def test_clear_active_task(self) -> None:
        """Function implementation."""
        wm = WorkingMemory()
        wm.set_active_task({"goal": "test"})
        wm.clear_active_task()
        assert wm.get_active_task() is None

    def test_active_task_deep_copied(self) -> None:
        """Function implementation."""
        wm = WorkingMemory()
        original = {"goal": "test", "items": [1]}
        wm.set_active_task(original)
        original["items"].append(2)
        assert wm.get_active_task()["items"] == [1]


class TestMemoryTierProtocol:

    def test_read_empty(self) -> None:
        """Function implementation."""
        wm = WorkingMemory()
        assert wm.read({}) == {}

    def test_read_returns_scratch_and_entries(self) -> None:
        """Function implementation."""
        wm = WorkingMemory()
        wm.put("key", "value")
        wm.add_entry("obs", {"x": 1})
        result = wm.read({})
        assert "scratch" in result
        assert result["scratch"]["key"] == "value"
        assert "entries" in result
        assert len(result["entries"]) == 1

    def test_read_returns_active_task(self) -> None:
        """Function implementation."""
        wm = WorkingMemory()
        wm.set_active_task({"goal": "go"})
        result = wm.read({})
        assert result["active_task"]["goal"] == "go"

    def test_write_adds_step_output_as_entry(self) -> None:
        """Function implementation."""
        wm = WorkingMemory()
        wm.write({
            "steps": {
                "summarize": {"summary": "bug in login"},
                "classify": {"severity": "high"},
            }
        })
        entries = wm.recent_entries()
        assert len(entries) == 1
        # write() adds the last step key
        assert entries[0]["step_id"] == "classify"

    def test_write_empty_steps_no_entry(self) -> None:
        """Function implementation."""
        wm = WorkingMemory()
        wm.write({"steps": {}})
        assert wm.recent_entries() == []


class TestReset:

    def test_reset_clears_everything(self) -> None:
        """Function implementation."""
        wm = WorkingMemory()
        wm.put("a", 1)
        wm.add_entry("e", {"x": 1})
        wm.set_active_task({"goal": "test"})
        wm.reset()
        assert wm.get("a") is None
        assert wm.recent_entries() == []
        assert wm.get_active_task() is None
        assert wm.read({}) == {}
