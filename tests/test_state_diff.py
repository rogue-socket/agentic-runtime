from __future__ import annotations

"""File: tests/test_state_diff.py

Purpose:
Validate deep path-level state diff generation.
"""

from agent_runtime.state import RuntimeState


def test_diff_paths_nested_changes() -> None:
    """Function implementation."""
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


def test_diff_paths_list_index_level_changes() -> None:
    """Function implementation."""
    before = {
        "steps": {
            "plan": {
                "tasks": ["a", "b"],
                "scores": [{"v": 1}],
            }
        }
    }
    after = {
        "steps": {
            "plan": {
                "tasks": ["a", "c", "d"],
                "scores": [{"v": 2}, {"v": 3}],
            }
        }
    }

    changes = RuntimeState.diff_paths(before, after)
    paths = {(c["op"], c["path"]) for c in changes}

    assert ("~", "steps.plan.tasks[1]") in paths
    assert ("+", "steps.plan.tasks[2]") in paths
    assert ("~", "steps.plan.scores[0].v") in paths
    assert ("+", "steps.plan.scores[1]") in paths


def test_diff_paths_list_index_removals() -> None:
    """Function implementation."""
    before = {"steps": {"items": [1, 2, 3]}}
    after = {"steps": {"items": [1]}}

    changes = RuntimeState.diff_paths(before, after)
    paths = {(c["op"], c["path"]) for c in changes}

    assert ("-", "steps.items[1]") in paths
    assert ("-", "steps.items[2]") in paths
