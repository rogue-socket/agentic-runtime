"""Tests for the ProceduralMemory stub."""

from __future__ import annotations

from agent_runtime.memory.procedural import ProceduralMemory


def test_initial_read_empty() -> None:
    mem = ProceduralMemory()
    assert mem.read({}) == {}


def test_write_then_read() -> None:
    mem = ProceduralMemory()
    mem.write({"rule": "always retry on 503", "confidence": 0.9})
    result = mem.read({})
    assert result == {"rule": "always retry on 503", "confidence": 0.9}


def test_write_replaces_previous() -> None:
    mem = ProceduralMemory()
    mem.write({"a": 1})
    mem.write({"b": 2})
    result = mem.read({})
    assert result == {"b": 2}
    assert "a" not in result


def test_read_returns_copy() -> None:
    """Mutating the returned dict should not affect internal state."""
    mem = ProceduralMemory()
    mem.write({"key": "value"})
    copy = mem.read({})
    copy["key"] = "mutated"
    assert mem.read({}) == {"key": "value"}


def test_write_stores_copy() -> None:
    """Mutating the input after write should not affect internal state."""
    mem = ProceduralMemory()
    payload = {"key": "value"}
    mem.write(payload)
    payload["key"] = "mutated"
    assert mem.read({}) == {"key": "value"}


def test_context_ignored() -> None:
    """Context argument is currently unused in the stub."""
    mem = ProceduralMemory()
    mem.write({"data": True})
    assert mem.read({"workflow_id": "test"}) == {"data": True}
