from __future__ import annotations

"""Live interactive debugger for runtime execution events.

The debugger operates on lifecycle events emitted by Executor/strategies and
blocks execution while waiting for user commands.
"""

import json
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from .utils import resolve_path, safe_eval
from .observability import _sanitize_trace_value


@dataclass
class Breakpoint:
    """Simple breakpoint matcher for event stream debugging."""

    kind: str
    value: str
    enabled: bool = True

    def matches(self, event: str, payload: Dict[str, Any]) -> bool:
        """Function implementation."""
        if not self.enabled:
            return False
        if self.kind == "event":
            return event == self.value
        if self.kind == "step":
            return str(payload.get("step_id", "")) == self.value
        if self.kind == "tool":
            return str(payload.get("tool_name", "")) == self.value
        if self.kind == "agent_step":
            candidate = payload.get("agent_pipeline_step")
            if candidate is None:
                candidate = payload.get("pipeline_step_id")  # Legacy key name — kept for backward compat with older persisted traces.
            return str(candidate or "") == self.value
        return False


def load_debug_profile(path: str) -> tuple[bool, List[str]]:
    """Load debugger profile from JSON.

    Expected structure:
    {
      "start_paused": true,
      "breakpoints": ["step:triage", "event:STEP_ERROR"]
    }
    """
    profile_path = Path(path)
    if not profile_path.is_file():
        raise ValueError(f"Debug profile not found: {path}")
    if profile_path.suffix.lower() != ".json":
        raise ValueError("Debug profile must be a .json file.")

    text = profile_path.read_text(encoding="utf-8")
    payload = json.loads(text)

    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError("Debug profile must be an object/map.")

    start_paused_raw = payload.get("start_paused", True)
    breakpoints_raw = payload.get("breakpoints", [])
    if not isinstance(start_paused_raw, bool):
        raise ValueError("Debug profile field 'start_paused' must be a boolean.")
    if not isinstance(breakpoints_raw, list) or not all(isinstance(x, str) for x in breakpoints_raw):
        raise ValueError("Debug profile field 'breakpoints' must be a list of strings.")

    return start_paused_raw, list(breakpoints_raw)


def save_debug_profile(path: str, *, start_paused: bool, breakpoints: List[str]) -> None:
    """Persist debugger profile as JSON."""
    profile_path = Path(path)
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    if profile_path.suffix.lower() != ".json":
        raise ValueError("Debug profile must be saved as a .json file.")
    payload = {
        "start_paused": bool(start_paused),
        "breakpoints": list(breakpoints),
    }
    profile_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


class LiveDebugger:
    """Interactive debugger over runtime events.

    Commands:
    - c / continue: Continue until next breakpoint.
    - s / step: Pause at next debuggable event.
    - n / next: Pause at next workflow step start.
    - i / into: From a workflow step, pause at first nested event for that step.
    - o / out: Continue until returning to shallower frame depth.
    - b <spec>: Add breakpoint (step:<id>, event:<name>, tool:<name>, agent_step:<id>).
    - bl: List breakpoints.
    - bd <index>: Delete breakpoint by index.
    - p [path]: Print latest state (or value at a dot path).
    - where: Show current location/event.
    - q / quit: Disable debugger and continue run.
    - h / help: Show commands.
    """

    DEBUG_EVENTS = {
        "STEP_START",
        "STEP_COMPLETE",
        "STEP_ERROR",
        "STEP_RETRY",
        "STEP_DEGRADED",
        "STEP_PROGRESS",
        "STEP_HEARTBEAT",
        "AGENT_ITERATION_START",
        "AGENT_ITERATION_COMPLETE",
        "AGENT_MODEL_START",
        "AGENT_MODEL_COMPLETE",
        "AGENT_TOOL_START",
        "AGENT_TOOL_COMPLETE",
        "AGENT_PIPELINE_TOOL_START",
        "AGENT_PIPELINE_TOOL_COMPLETE",
    }

    def __init__(
        self,
        *,
        load_latest_state: Callable[[str], Dict[str, Any]],
        breakpoints: Optional[List[str]] = None,
        start_paused: bool = True,
        event_log_dir: Optional[str] = ".runs",
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], None] = print,
    ) -> None:
        """Function implementation."""
        self._load_latest_state = load_latest_state
        self._input = input_fn
        self._output = output_fn
        self.enabled = True

        self._breakpoints: List[Breakpoint] = []
        for spec in breakpoints or []:
            bp = self._parse_breakpoint(spec)
            if bp is not None:
                self._breakpoints.append(bp)

        self._pause_once = start_paused
        self._next_step_execution_index: Optional[int] = None
        self._into_target: Optional[tuple[str, str, int]] = None
        self._out_target_depth: Optional[int] = None
        self._event_log_dir = Path(event_log_dir) if event_log_dir else None

        self.pause_count = 0

    def handle_event(self, event: str, payload: Dict[str, Any]) -> None:
        """Event callback used as Executor.on_event."""
        if not self.enabled:
            return
        if event not in self.DEBUG_EVENTS:
            return

        self._log_event(event, payload)

        depth = self._event_depth(event)
        should_pause = self._should_pause(event, payload, depth)
        if not should_pause:
            return

        self.pause_count += 1
        self._render_pause_banner(event, payload)
        self._command_loop(event, payload, depth)

    def _should_pause(self, event: str, payload: Dict[str, Any], depth: int) -> bool:
        """Function implementation."""
        if self._pause_once:
            self._pause_once = False
            return True

        if self._next_step_execution_index is not None and event == "STEP_START":
            current_idx = payload.get("execution_index")
            if isinstance(current_idx, int) and current_idx >= self._next_step_execution_index:
                self._next_step_execution_index = None
                return True

        if self._into_target is not None:
            run_id, step_id, execution_index = self._into_target
            same_scope = (
                str(payload.get("run_id", "")) == run_id
                and str(payload.get("step_id", "")) == step_id
                and int(payload.get("execution_index") or -1) == execution_index
            )
            if same_scope and depth > 1:
                self._into_target = None
                return True
            if event in {"STEP_COMPLETE", "STEP_ERROR"} and same_scope:
                self._into_target = None
                return True

        if self._out_target_depth is not None and depth <= self._out_target_depth:
            self._out_target_depth = None
            return True

        for bp in self._breakpoints:
            if bp.kind == "expr":
                if self._evaluate_expression_breakpoint(bp.value, payload):
                    return True
                continue
            if bp.matches(event, payload):
                return True

        return False

    def _event_depth(self, event: str) -> int:
        """Function implementation."""
        if event.startswith("AGENT_"):
            return 2
        if event in {"STEP_PROGRESS", "STEP_HEARTBEAT"}:
            return 2
        if event.startswith("STEP_"):
            return 1
        return 0

    def _render_pause_banner(self, event: str, payload: Dict[str, Any]) -> None:
        """Function implementation."""
        step_id = payload.get("step_id", "-")
        step_type = payload.get("step_type", "-")
        exec_idx = payload.get("execution_index", "-")
        self._output(
            f"\n[debug] Paused on {event} | step={step_id} ({step_type}) | execution_index={exec_idx}"
        )

    def _command_loop(self, event: str, payload: Dict[str, Any], depth: int) -> None:
        """Function implementation."""
        while True:
            try:
                raw = self._input("(debug) ").strip()
            except EOFError:
                raw = "c"

            if not raw:
                raw = "c"

            cmd, _, arg = raw.partition(" ")
            cmd = cmd.lower()
            arg = arg.strip()

            if cmd in {"c", "continue"}:
                return

            if cmd in {"s", "step"}:
                self._pause_once = True
                return

            if cmd in {"n", "next"}:
                current_idx = payload.get("execution_index")
                if isinstance(current_idx, int):
                    self._next_step_execution_index = current_idx + 1
                else:
                    self._pause_once = True
                return

            if cmd in {"i", "into"}:
                run_id = str(payload.get("run_id", ""))
                step_id = str(payload.get("step_id", ""))
                exec_idx = payload.get("execution_index")
                if run_id and step_id and isinstance(exec_idx, int):
                    self._into_target = (run_id, step_id, exec_idx)
                else:
                    self._pause_once = True
                return

            if cmd in {"o", "out"}:
                self._out_target_depth = max(0, depth - 1)
                return

            if cmd == "b":
                if not arg:
                    self._output(
                        "Usage: b step:<id> | event:<name> | tool:<name> | agent_step:<id> | expr:<condition>"
                    )
                    continue
                bp = self._parse_breakpoint(arg)
                if bp is None:
                    self._output("Invalid breakpoint format.")
                    continue
                self._breakpoints.append(bp)
                self._output(f"Added breakpoint #{len(self._breakpoints)}: {bp.kind}:{bp.value}")
                continue

            if cmd == "save":
                if not arg:
                    self._output("Usage: save <path>")
                    continue
                try:
                    save_debug_profile(
                        arg,
                        start_paused=False,
                        breakpoints=self._breakpoint_specs(),
                    )
                except Exception as exc:  # noqa: BLE001
                    self._output(f"Failed to save profile: {type(exc).__name__}: {exc}")
                    continue
                self._output(f"Saved debug profile to {arg}")
                continue

            if cmd == "bl":
                self._list_breakpoints()
                continue

            if cmd == "bd":
                if not arg.isdigit():
                    self._output("Usage: bd <index>")
                    continue
                index = int(arg)
                if index < 1 or index > len(self._breakpoints):
                    self._output("Breakpoint index out of range.")
                    continue
                removed = self._breakpoints.pop(index - 1)
                self._output(f"Removed breakpoint: {removed.kind}:{removed.value}")
                continue

            if cmd == "where":
                self._output(f"event={event} payload={payload}")
                continue

            if cmd in {"p", "print"}:
                self._print_state(payload, arg)
                continue

            if cmd in {"q", "quit"}:
                self.enabled = False
                self._output("Debugger disabled for this run.")
                return

            if cmd in {"h", "help", "?"}:
                self._output(self._help_text())
                continue

            self._output("Unknown command. Type 'h' for help.")

    def _list_breakpoints(self) -> None:
        """Function implementation."""
        if not self._breakpoints:
            self._output("No breakpoints.")
            return
        for idx, bp in enumerate(self._breakpoints, start=1):
            self._output(f"{idx}. {bp.kind}:{bp.value}")

    def _print_state(self, payload: Dict[str, Any], path: str) -> None:
        """Function implementation."""
        run_id = str(payload.get("run_id", ""))
        if not run_id:
            self._output("No run_id in current payload.")
            return
        try:
            state = self._load_latest_state(run_id)
        except Exception as exc:  # noqa: BLE001
            self._output(f"Unable to load state: {type(exc).__name__}: {exc}")
            return

        if not path:
            self._output(str(_sanitize_trace_value(state)))
            return

        try:
            value = resolve_path(path, state)
        except Exception as exc:  # noqa: BLE001
            self._output(f"Path lookup failed: {type(exc).__name__}: {exc}")
            return
        self._output(str(_sanitize_trace_value(value)))

    def _parse_breakpoint(self, spec: str) -> Optional[Breakpoint]:
        """Function implementation."""
        raw = spec.strip()
        if not raw:
            return None
        if ":" not in raw:
            return Breakpoint(kind="step", value=raw)

        kind, _, value = raw.partition(":")
        kind = kind.strip().lower()
        value = value.strip()
        if not value:
            return None
        if kind not in {"event", "step", "tool", "agent_step", "expr"}:
            return None
        return Breakpoint(kind=kind, value=value)

    def _breakpoint_specs(self) -> List[str]:
        """Function implementation."""
        return [f"{bp.kind}:{bp.value}" for bp in self._breakpoints]

    def _evaluate_expression_breakpoint(self, expression: str, payload: Dict[str, Any]) -> bool:
        """Function implementation."""
        run_id = str(payload.get("run_id", ""))
        if not run_id:
            return False

        try:
            latest_state = self._load_latest_state(run_id)
        except Exception:
            return False

        if not isinstance(latest_state, dict):
            return False

        debug_state = dict(latest_state)
        debug_state["event"] = payload
        try:
            return bool(safe_eval(expression, debug_state))
        except Exception:
            return False

    def _log_event(self, event: str, payload: Dict[str, Any]) -> None:
        """Function implementation."""
        if self._event_log_dir is None:
            return
        run_id = str(payload.get("run_id", ""))
        if not run_id:
            return
        try:
            run_dir = self._event_log_dir / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            log_path = run_dir / "debug_events.jsonl"
            entry = {
                "event": event,
                "payload": _sanitize_trace_value(payload),
            }
            with log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=True, default=str) + "\n")
        except Exception:
            # Logging should never break execution.
            return

    def _help_text(self) -> str:
        """Function implementation."""
        return (
            "Commands: c(continue), s(step), n(next), i(into), o(out), "
            "b <spec>, bl, bd <index>, save <path>, p [path], where, q(quit debugger), h(help)"
        )
