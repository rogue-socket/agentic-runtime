from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..state import RuntimeState
from .run_loader import RunVisualizationData


@dataclass
class StateDelta:
    op: str
    path: str
    before: Any
    after: Any


@dataclass
class StepTimelineItem:
    step_id: str
    step_type: str
    status: str
    attempts: int
    duration_ms: Optional[int]
    started_at: Optional[str]
    finished_at: Optional[str]
    input_data: Optional[Dict[str, Any]]
    output_data: Optional[Dict[str, Any]]
    error: Optional[str]
    last_error: Optional[str]
    tool_name: Optional[str]
    state_changes: List[StateDelta]


@dataclass
class TimelineView:
    initial_state: Dict[str, Any]
    steps: List[StepTimelineItem]
    latest_state: Dict[str, Any]


class TimelineBuilder:
    def build(self, data: RunVisualizationData) -> TimelineView:
        items: List[StepTimelineItem] = []
        for step in data.steps:
            before = step.state_before or {}
            after = step.state_after or {}
            changes = [
                StateDelta(op=change["op"], path=change["path"], before=change.get("before"), after=change.get("after"))
                for change in RuntimeState.diff_paths(before, after)
            ]
            tool_name = None
            if step.step_type == "tool":
                meta = data.step_meta.get(step.step_id)
                tool_name = meta.tool_name if meta else None
            items.append(
                StepTimelineItem(
                    step_id=step.step_id,
                    step_type=step.step_type,
                    status=step.status,
                    attempts=step.attempt_count or 1,
                    duration_ms=step.duration_ms,
                    started_at=step.started_at,
                    finished_at=step.finished_at,
                    input_data=step.input,
                    output_data=step.output,
                    error=step.error,
                    last_error=step.last_error,
                    tool_name=tool_name,
                    state_changes=changes,
                )
            )

        return TimelineView(initial_state=data.initial_state, steps=items, latest_state=data.latest_state)
