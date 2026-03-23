from __future__ import annotations

"""LLM shared types for requests/responses."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Native function-calling types
# ---------------------------------------------------------------------------
# TODO(native-function-calling — Phase 1: Data Model)
#
# These types are the contract between adapters and the agent strategy layer.
# An adapter that supports native function calling should populate
# `LLMResponse.tool_calls` instead of (or in addition to) `text`.
#
# WHAT TO DO:
#   • No changes needed here for Phase 1 — the data model is ready.
#   • See adapters.py for where to populate these.
# ---------------------------------------------------------------------------


@dataclass
class ToolCallRequest:
    """A single native tool-call emitted by the LLM (function-calling API).

    Populated by adapters that support native function calling
    (OpenAI ``tool_calls``, Anthropic ``tool_use``, Gemini ``functionCall``).
    Currently always empty — text-based parsing is the live path.

    Fields:
        id         -- Provider-assigned call ID (used to correlate the result
                      in the follow-up user message).
        tool_name  -- Name of the tool the model wants to invoke.
        tool_input -- Parsed JSON arguments supplied by the model.
    """

    id: str
    tool_name: str
    tool_input: Dict[str, Any]


@dataclass
class LLMResponse:
    """Normalized LLM response returned by adapters."""

    text: str
    provider: str
    model: str
    usage: Optional[Dict[str, Any]] = None
    raw: Optional[Dict[str, Any]] = None
    # Populated by adapters that support native function calling.
    # Empty list = the model responded with text only (current default).
    tool_calls: List[ToolCallRequest] = field(default_factory=list)
