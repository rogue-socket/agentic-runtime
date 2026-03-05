from __future__ import annotations

from agent_runtime.cli import _diff_state


def test_diff_state_basic() -> None:
    before = {"inputs": {"issue": "x"}, "steps": {}}
    after = {"inputs": {"issue": "x"}, "steps": {"a": {"ok": True}}}
    diff = _diff_state(before, after)
    assert "steps" in diff["changed"] or "steps" in diff["added"]
