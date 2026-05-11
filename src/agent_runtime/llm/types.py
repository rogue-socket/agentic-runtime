from __future__ import annotations

"""LLM shared types for requests/responses."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Native function-calling types
# ---------------------------------------------------------------------------
# [DONE — All phases complete] Data model, adapters, and strategies all
# support native function calling. OpenAI, Anthropic, and Gemini adapters
# populate LLMResponse.tool_calls via their native APIs.
# ---------------------------------------------------------------------------


@dataclass
class ToolCallRequest:
    """A single native tool-call emitted by the LLM (function-calling API).

    Populated by all three adapters via native function calling
    (OpenAI ``tool_calls``, Anthropic ``tool_use``, Gemini ``functionCall``).

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
    # Set by LLMClient.call() after pricing lookup; None when pricing unconfigured.
    cost_usd: Optional[float] = None
