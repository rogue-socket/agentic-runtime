from __future__ import annotations

import json
from typing import Dict

from agent_runtime.debugger import LiveDebugger, load_debug_profile, save_debug_profile


class _InputScript:
    def __init__(self, commands: list[str]) -> None:
        self._commands = iter(commands)

    def __call__(self, _: str) -> str:
        return next(self._commands, "c")


def _payload(
    *,
    run_id: str = "run-1",
    step_id: str = "step-1",
    step_type: str = "function",
    execution_index: int = 1,
) -> Dict[str, object]:
    return {
        "run_id": run_id,
        "step_id": step_id,
        "step_type": step_type,
        "execution_index": execution_index,
    }


def test_debugger_pauses_on_first_debug_event() -> None:
    outputs: list[str] = []
    debugger = LiveDebugger(
        load_latest_state=lambda _run_id: {},
        start_paused=True,
        input_fn=_InputScript(["c"]),
        output_fn=outputs.append,
    )

    debugger.handle_event("STEP_START", _payload())

    assert debugger.pause_count == 1
    assert any("Paused on STEP_START" in line for line in outputs)


def test_breakpoint_by_step_id() -> None:
    debugger = LiveDebugger(
        load_latest_state=lambda _run_id: {},
        breakpoints=["step:target"],
        start_paused=False,
        input_fn=_InputScript(["c"]),
        output_fn=lambda _msg: None,
    )

    debugger.handle_event("STEP_START", _payload(step_id="other", execution_index=1))
    debugger.handle_event("STEP_START", _payload(step_id="target", execution_index=2))

    assert debugger.pause_count == 1


def test_next_command_pauses_on_next_workflow_step() -> None:
    debugger = LiveDebugger(
        load_latest_state=lambda _run_id: {},
        start_paused=True,
        input_fn=_InputScript(["n", "c"]),
        output_fn=lambda _msg: None,
    )

    debugger.handle_event("STEP_START", _payload(execution_index=1))
    debugger.handle_event(
        "AGENT_MODEL_START",
        _payload(step_type="agent", execution_index=1),
    )
    debugger.handle_event("STEP_START", _payload(execution_index=2))

    assert debugger.pause_count == 2


def test_into_command_pauses_on_nested_event() -> None:
    debugger = LiveDebugger(
        load_latest_state=lambda _run_id: {},
        start_paused=True,
        input_fn=_InputScript(["i", "c"]),
        output_fn=lambda _msg: None,
    )

    debugger.handle_event(
        "STEP_START",
        _payload(step_id="review", step_type="agent", execution_index=3),
    )
    debugger.handle_event(
        "AGENT_MODEL_START",
        _payload(step_id="review", step_type="agent", execution_index=3),
    )

    assert debugger.pause_count == 2


def test_out_command_pauses_when_returning_to_shallower_depth() -> None:
    debugger = LiveDebugger(
        load_latest_state=lambda _run_id: {},
        start_paused=True,
        input_fn=_InputScript(["o", "c"]),
        output_fn=lambda _msg: None,
    )

    debugger.handle_event("AGENT_MODEL_START", _payload(step_type="agent", execution_index=2))
    debugger.handle_event("STEP_PROGRESS", _payload(step_type="agent", execution_index=2))
    debugger.handle_event("STEP_COMPLETE", _payload(step_type="agent", execution_index=2))

    assert debugger.pause_count == 2


def test_expression_breakpoint_matches_payload_state() -> None:
    debugger = LiveDebugger(
        load_latest_state=lambda _run_id: {
            "inputs": {"priority": "high"},
            "steps": {},
            "runtime": {},
        },
        breakpoints=["expr:state.event.step_id == 'triage' and state.inputs.priority == 'high'"],
        start_paused=False,
        input_fn=_InputScript(["c"]),
        output_fn=lambda _msg: None,
    )

    debugger.handle_event("STEP_START", _payload(step_id="triage", execution_index=1))

    assert debugger.pause_count == 1


def test_debug_profile_roundtrip_json(tmp_path) -> None:
    profile_path = tmp_path / "debug-profile.json"
    save_debug_profile(
        str(profile_path),
        start_paused=False,
        breakpoints=["step:triage", "event:STEP_ERROR"],
    )

    start_paused, breakpoints = load_debug_profile(str(profile_path))

    assert start_paused is False
    assert breakpoints == ["step:triage", "event:STEP_ERROR"]


def test_debugger_persists_event_log(tmp_path) -> None:
    debugger = LiveDebugger(
        load_latest_state=lambda _run_id: {},
        start_paused=False,
        event_log_dir=str(tmp_path),
        input_fn=_InputScript(["c"]),
        output_fn=lambda _msg: None,
    )

    debugger.handle_event("STEP_START", _payload(run_id="run-42", step_id="s1", execution_index=1))

    log_path = tmp_path / "run-42" / "debug_events.jsonl"
    assert log_path.is_file()
    entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert entries
    assert entries[0]["event"] == "STEP_START"
