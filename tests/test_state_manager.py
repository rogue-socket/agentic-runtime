from __future__ import annotations

"""File: tests/test_state_manager.py

Purpose:
Validate RuntimeState mutation, isolation, and diff behavior.
"""

from agent_runtime.state import RuntimeState


def test_set_get() -> None:
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> test_set_get
        >>> # Example 2
        >>> test_set_get
    """
    state = RuntimeState({"inputs": {"issue": "x"}, "steps": {}, "runtime": {}})
    state.set("runtime.mode", "test", step_name="executor")
    assert state.get("runtime.mode") == "test"


def test_step_output_isolation() -> None:
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> test_step_output_isolation
        >>> # Example 2
        >>> test_step_output_isolation
    """
    state = RuntimeState({"inputs": {"issue": "x"}, "steps": {}, "runtime": {}})
    state.set_step_output("step_a", {"summary": "a"})
    state.set_step_output("step_b", {"summary": "b"})
    as_dict = state.to_dict()
    assert as_dict["steps"]["step_a"]["summary"] == "a"
    assert as_dict["steps"]["step_b"]["summary"] == "b"


def test_snapshot_is_copy() -> None:
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> test_snapshot_is_copy
        >>> # Example 2
        >>> test_snapshot_is_copy
    """
    state = RuntimeState({"inputs": {"issue": "x"}, "steps": {}, "runtime": {}})
    snap = state.snapshot()
    snap["inputs"]["issue"] = "y"
    assert state.get("inputs.issue") == "x"


def test_diff() -> None:
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> test_diff
        >>> # Example 2
        >>> test_diff
    """
    before = {"inputs": {"issue": "x"}, "steps": {}, "runtime": {}}
    after = {"inputs": {"issue": "x"}, "steps": {"a": {"ok": True}}, "runtime": {}}
    diff = RuntimeState.diff(before, after)
    assert "steps" in diff["changed"] or "steps" in diff["added"]


def test_overwrite_warning(capsys) -> None:
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> test_overwrite_warning
        >>> # Example 2
        >>> test_overwrite_warning
    """
    state = RuntimeState({"inputs": {"issue": "x"}, "steps": {}, "runtime": {}})
    state.set("runtime.flag", True, step_name="s1")
    state.set("runtime.flag", False, step_name="s2")
    captured = capsys.readouterr()
    assert "STATE WARNING" in captured.out
