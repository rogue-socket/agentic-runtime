from __future__ import annotations

from agent_runtime.state import RuntimeState


def test_set_get() -> None:
    state = RuntimeState({"inputs": {"issue": "x"}, "steps": {}, "runtime": {}})
    state.set("runtime.mode", "test", step_name="executor")
    assert state.get("runtime.mode") == "test"


def test_step_output_isolation() -> None:
    state = RuntimeState({"inputs": {"issue": "x"}, "steps": {}, "runtime": {}})
    state.set_step_output("step_a", {"summary": "a"})
    state.set_step_output("step_b", {"summary": "b"})
    as_dict = state.to_dict()
    assert as_dict["steps"]["step_a"]["summary"] == "a"
    assert as_dict["steps"]["step_b"]["summary"] == "b"


def test_snapshot_is_copy() -> None:
    state = RuntimeState({"inputs": {"issue": "x"}, "steps": {}, "runtime": {}})
    snap = state.snapshot()
    snap["inputs"]["issue"] = "y"
    assert state.get("inputs.issue") == "x"


def test_diff() -> None:
    before = {"inputs": {"issue": "x"}, "steps": {}, "runtime": {}}
    after = {"inputs": {"issue": "x"}, "steps": {"a": {"ok": True}}, "runtime": {}}
    diff = RuntimeState.diff(before, after)
    assert "steps" in diff["changed"] or "steps" in diff["added"]


def test_overwrite_warning(capsys) -> None:
    state = RuntimeState({"inputs": {"issue": "x"}, "steps": {}, "runtime": {}})
    state.set("runtime.flag", True, step_name="s1")
    state.set("runtime.flag", False, step_name="s2")
    captured = capsys.readouterr()
    assert "STATE WARNING" in captured.out
