"""Tests for the ProceduralMemory stub."""

from __future__ import annotations

from agent_runtime.memory.procedural import ProceduralMemory


def _wrap(store: dict) -> dict:
    """Wrap a flat store dict in the expected namespace."""
    return {"runtime": {"memory": {"procedural": {"store": store}}}}


def test_initial_read_empty() -> None:
    mem = ProceduralMemory()
    assert mem.read({}) == {}


def test_write_then_read() -> None:
    mem = ProceduralMemory()
    mem.write(_wrap({"rule": "always retry on 503", "confidence": 0.9}))
    result = mem.read({})
    assert result == {"rule": "always retry on 503", "confidence": 0.9}


def test_write_merges_previous() -> None:
    mem = ProceduralMemory()
    mem.write(_wrap({"a": 1}))
    mem.write(_wrap({"b": 2}))
    result = mem.read({})
    assert result == {"a": 1, "b": 2}


def test_read_returns_copy() -> None:
    """Mutating the returned dict should not affect internal state."""
    mem = ProceduralMemory()
    mem.write(_wrap({"key": "value"}))
    copy = mem.read({})
    copy["key"] = "mutated"
    assert mem.read({}) == {"key": "value"}


def test_write_stores_copy() -> None:
    """Mutating the input after write should not affect internal state."""
    mem = ProceduralMemory()
    store = {"key": "value"}
    mem.write(_wrap(store))
    store["key"] = "mutated"
    assert mem.read({}) == {"key": "value"}


def test_context_ignored() -> None:
    """Context argument is currently unused in the stub."""
    mem = ProceduralMemory()
    mem.write(_wrap({"data": True}))
    assert mem.read({"workflow_id": "test"}) == {"data": True}


def test_write_ignores_payload_without_store() -> None:
    """Payload without the expected namespace is a no-op."""
    mem = ProceduralMemory()
    mem.write({"random": "data"})
    assert mem.read({}) == {}
