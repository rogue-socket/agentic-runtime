from __future__ import annotations

"""Observability helpers shared across runtime, CLI, and replay paths."""

from typing import Any, Dict, Iterable, List, Optional, Sequence
import re


_TEXT_REDACTION_PATTERNS = [
    # Common provider token prefixes.
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), "[REDACTED_API_KEY]"),
    # Generic bearer tokens.
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~-]{8,}"), "Bearer [REDACTED]"),
    # Credential assignment forms (password=..., token: ..., api_key=...).
    (
        re.compile(r"(?i)\b(api[_-]?key|token|password|secret)\b\s*[:=]\s*([\"']?)[^\s,;\"']+\2"),
        lambda m: f"{m.group(1)}=[REDACTED]",
    ),
    # Basic email patterns.
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[REDACTED_EMAIL]"),
    # Long digit sequences that may include credit card / account values.
    (re.compile(r"\b\d{13,19}\b"), "[REDACTED_NUMBER]"),
]


def _redact_sensitive_text(text: str) -> str:
    """Redact common credential and PII patterns in free text."""
    redacted = text
    for pattern, replacement in _TEXT_REDACTION_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def _sanitize_trace_value(value: Any) -> Any:
    """Recursively sanitize trace payload values before persistence."""
    if isinstance(value, str):
        return _redact_sensitive_text(value)
    if isinstance(value, dict):
        return {k: _sanitize_trace_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_trace_value(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_trace_value(v) for v in value)
    return value


def percentile(values: Sequence[float], pct: float) -> Optional[float]:
    """Compute a percentile from numeric values.

    Uses linear interpolation between adjacent sorted values.
    Returns ``None`` when input is empty.
    """
    if not values:
        return None
    if pct <= 0:
        return float(min(values))
    if pct >= 100:
        return float(max(values))

    sorted_values = sorted(float(v) for v in values)
    index = (len(sorted_values) - 1) * (pct / 100.0)
    lower = int(index)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = index - lower
    return sorted_values[lower] + ((sorted_values[upper] - sorted_values[lower]) * fraction)


def serialize_agent_trace(turns: Iterable[Any]) -> List[Dict[str, Any]]:
    """Serialize AgentTurn-like objects into a stable trace schema.

    Output schema emits flat ``model`` and ``tool`` events so downstream
    CLI/replay renderers can print traces consistently.
    """
    events: List[Dict[str, Any]] = []

    for turn in turns:
        iteration = getattr(turn, "iteration", None)
        llm_request = getattr(turn, "llm_request", None)
        llm_response = getattr(turn, "llm_response", None)

        response_text = None
        model = ""
        usage = None
        if llm_response is not None:
            response_text = getattr(llm_response, "text", None)
            model = str(getattr(llm_response, "model", "") or "")
            usage = getattr(llm_response, "usage", None)

        if llm_request is not None or llm_response is not None:
            model_event: Dict[str, Any] = {
                "type": "model",
                "iteration": iteration,
                "model": model,
                "response_text": _sanitize_trace_value(response_text),
                "llm_request": _sanitize_trace_value(llm_request),
            }
            if usage is not None:
                model_event["usage"] = _sanitize_trace_value(usage)
            events.append(model_event)

        for tool_call in getattr(turn, "tool_calls", []) or []:
            result = getattr(tool_call, "result", None)
            tool_event: Dict[str, Any] = {
                "type": "tool",
                "iteration": iteration,
                "tool": getattr(tool_call, "tool_name", ""),
                "input": _sanitize_trace_value(getattr(tool_call, "tool_input", None)),
                "duration_ms": getattr(tool_call, "duration_ms", None),
                "success": getattr(result, "success", None) if result is not None else None,
                "error": _sanitize_trace_value(getattr(result, "error", None)) if result is not None else None,
                "output": _sanitize_trace_value(getattr(result, "output", None)) if result is not None else None,
            }
            events.append(tool_event)

    return events


def _extract_legacy_model_name(entry: Dict[str, Any]) -> str:
    """Extract model name from a legacy trace entry's llm_request."""
    llm_request = entry.get("llm_request")
    if isinstance(llm_request, dict):
        return str(llm_request.get("model", "") or "")
    return ""


def normalize_agent_trace(trace: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize mixed trace formats (legacy/current) into flat model/tool events."""
    normalized: List[Dict[str, Any]] = []

    for entry in trace or []:
        if not isinstance(entry, dict):
            continue

        trace_type = entry.get("type")
        if trace_type in {"model", "tool"}:
            normalized.append(entry)
            continue

        # Legacy shape used one entry per iteration with nested tool_calls.
        if "llm_request" in entry or "llm_response_text" in entry or "tool_calls" in entry:
            normalized.append(
                {
                    "type": "model",
                    "iteration": entry.get("iteration"),
                    "model": _extract_legacy_model_name(entry),
                    "response_text": entry.get("llm_response_text"),
                    "llm_request": entry.get("llm_request"),
                }
            )
            tool_calls = entry.get("tool_calls")
            if isinstance(tool_calls, list):
                for tool_call in tool_calls:
                    if not isinstance(tool_call, dict):
                        continue
                    normalized.append(
                        {
                            "type": "tool",
                            "iteration": entry.get("iteration"),
                            "tool": tool_call.get("tool", ""),
                            "input": tool_call.get("input"),
                            "success": tool_call.get("success"),
                            "duration_ms": tool_call.get("duration_ms"),
                            "error": tool_call.get("error"),
                            "output": tool_call.get("output"),
                        }
                    )
            continue

        # Unknown shape: preserve as unknown event for debugging.
        normalized.append({"type": "unknown", "raw": entry})

    return normalized
