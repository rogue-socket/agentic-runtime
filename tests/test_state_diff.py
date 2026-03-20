# TODO(H3-high): This file contains 1 junk auto-generated docstring
#   that should be replaced with a real description or removed entirely.
from __future__ import annotations

"""File: tests/test_state_diff.py

Purpose:
Validate deep path-level state diff generation.
"""

from agent_runtime.state import RuntimeState


def test_diff_paths_nested_changes() -> None:
    """Auto-generated documentation for this callable.
    
    Describes purpose, expected inputs/outputs, and behavior in this module.
    
    Example:
        >>> # Example 1
        >>> test_diff_paths_nested_changes
        >>> # Example 2
        >>> test_diff_paths_nested_changes
    """
    before = {
        "inputs": {"issue": "x"},
        "steps": {"plan": {"draft_message": "hello"}},
        "runtime": {},
    }
    after = {
        "inputs": {"issue": "x"},
        "steps": {
            "plan": {
                "tasks": ["a", "b"],
                "priority": "high",
            }
        },
        "runtime": {},
    }

    changes = RuntimeState.diff_paths(before, after)
    paths = {(c["op"], c["path"]) for c in changes}

    assert ("+", "steps.plan.tasks") in paths
    assert ("+", "steps.plan.priority") in paths
    assert ("-", "steps.plan.draft_message") in paths
