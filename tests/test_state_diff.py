from __future__ import annotations

"""File: tests/test_state_diff.py

Purpose:
Validate deep path-level state diff generation.
"""

from agent_runtime.state import RuntimeState


def test_diff_paths_nested_changes() -> None:
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
