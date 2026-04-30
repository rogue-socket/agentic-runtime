"""Typed lifecycle event dataclasses for SDK consumers.

The Executor emits events as ``(event_name: str, payload: dict)`` pairs
via the raw :data:`EventCallback` protocol.  This module provides typed
dataclasses and an adapter so SDK users get IDE autocomplete and type
safety without changing the Executor internals.

Usage::

    from agent_runtime.events import adapt_typed_callback, StepCompleteEvent

    def on_event(event):
        if isinstance(event, StepCompleteEvent):
            print(f"{event.step_id} finished in {event.duration_ms}ms")

    runtime = RuntimeBuilder().with_on_event(on_event).build()
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Union


@dataclass(frozen=True)
class RunStartEvent:
    """Emitted when a workflow run begins."""

    run_id: str
    workflow_id: str


@dataclass(frozen=True)
class StepStartEvent:
    """Emitted when a step begins execution."""

    run_id: str
    step_id: str
    step_type: str
    execution_index: int


@dataclass(frozen=True)
class StepCompleteEvent:
    """Emitted when a step completes successfully."""

    run_id: str
    step_id: str
    step_type: str
    duration_ms: int
    attempt_count: int
    tool_duration_ms: Optional[int] = None


@dataclass(frozen=True)
class StepErrorEvent:
    """Emitted when a step fails after all retries."""

    run_id: str
    step_id: str
    step_type: str
    error: str
    attempt_count: int
    duration_ms: Optional[int] = None


@dataclass(frozen=True)
class RunCompleteEvent:
    """Emitted when a workflow run finishes (success or failure)."""

    run_id: str
    status: str
    error: Optional[str] = None


# Union of all typed events.
Event = Union[RunStartEvent, StepStartEvent, StepCompleteEvent, StepErrorEvent, RunCompleteEvent]

# Typed callback signature for SDK users.
TypedEventCallback = Callable[[Event], None]

# Mapping from raw event name to parser.
_EVENT_PARSERS: Dict[str, type] = {
    "RUN_START": RunStartEvent,
    "STEP_START": StepStartEvent,
    "STEP_COMPLETE": StepCompleteEvent,
    "STEP_ERROR": StepErrorEvent,
    "RUN_COMPLETE": RunCompleteEvent,
}

# Fields accepted by each event dataclass (used for filtering payload keys).
_EVENT_FIELDS: Dict[str, set] = {
    name: {f.name for f in cls.__dataclass_fields__.values()}
    for name, cls in _EVENT_PARSERS.items()
}


def _parse_event(event_name: str, payload: Dict[str, Any]) -> Optional[Event]:
    """Convert a raw ``(name, payload)`` pair to a typed event.

    Returns ``None`` for event names that have no typed counterpart
    (e.g. ``STEP_HEARTBEAT``, ``STEP_RETRY``).
    """
    cls = _EVENT_PARSERS.get(event_name)
    if cls is None:
        return None
    # Filter payload to only fields the dataclass accepts.
    fields = _EVENT_FIELDS[event_name]
    filtered = {k: v for k, v in payload.items() if k in fields}
    try:
        return cls(**filtered)
    except TypeError:
        return None


def adapt_typed_callback(typed_cb: TypedEventCallback) -> Callable[[str, Dict[str, Any]], None]:
    """Wrap a :data:`TypedEventCallback` into a raw ``EventCallback``.

    Events that have no typed counterpart are silently dropped.
    """
    def wrapper(event_name: str, payload: Dict[str, Any]) -> None:
        event = _parse_event(event_name, payload)
        if event is not None:
            typed_cb(event)
    return wrapper
