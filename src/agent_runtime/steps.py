from __future__ import annotations

"""Deprecated: model-step handler registry.

This module is retained only for backward compatibility with existing tests
that use ``type: model`` workflow steps.  New workflows should use
``type: function`` (backed by functions/) or ``type: agent`` instead.

Only ``StepHandlerRegistry`` and ``generate_summary`` are still referenced.
"""

import warnings

warnings.warn(
    "agent_runtime.steps is deprecated — use type: function or type: agent steps instead",
    DeprecationWarning,
    stacklevel=2,
)

from typing import Any, Callable, Dict

from .errors import HandlerNotFoundError
from .state import RuntimeState

StateDict = Dict[str, Any]
StepHandler = Callable[..., StateDict]


class StepHandlerRegistry:
    """Registry of named model handlers used by workflow loader/executor.

    Workflow parsing resolves handler names through this registry so
    execution can dispatch model steps without dynamic imports.

    Example:
        >>> reg = StepHandlerRegistry()
        >>> reg.register("h", lambda s: {"ok": True})
    """

    def __init__(self) -> None:
        """Initialize empty handler mapping."""
        self._handlers: Dict[str, StepHandler] = {}

    def register(self, name: str, handler: StepHandler) -> None:
        """Register or replace a handler under a name.

        Args:
            name: Workflow-facing handler identifier.
            handler: Callable taking `RuntimeState` and returning dict.

        Example:
            >>> reg = StepHandlerRegistry()
            >>> reg.register("sum", generate_summary)
        """
        self._handlers[name] = handler

    def get(self, name: str) -> StepHandler:
        """Return a registered handler by name.

        Raises:
            HandlerNotFoundError: If name is unknown.

        Example:
            >>> reg = StepHandlerRegistry(); reg.register("x", lambda s: {})
            >>> callable(reg.get("x"))
            True
        """
        if name not in self._handlers:
            raise HandlerNotFoundError(f"Handler not found: {name}")
        return self._handlers[name]


def generate_summary(state: RuntimeState) -> StateDict:
    """Generate deterministic summary text from issue input.

    This scaffold implementation intentionally avoids external model
    calls so tests and examples stay deterministic and fast.

    Args:
        state: Input state expected to contain non-empty `issue` string.

    Returns:
        Dictionary containing a single `summary` field.

    Example:
        >>> generate_summary(RuntimeState({"issue": "Login API fails for invalid token"}, enforce_structure=False))
        {'summary': 'Issue related to login api failing when invalid token.'}
        >>> generate_summary(RuntimeState({"issue": "Bug"}, enforce_structure=False))["summary"]
        'Issue related to bug.'
    """
    # [SCAFFOLD:LLM] Replace deterministic summary with model-backed generation.
    if "issue" not in state:
        raise KeyError("Missing required key: issue")
    issue = state["issue"]
    if not isinstance(issue, str) or not issue.strip():
        raise ValueError("issue must be a non-empty string")

    normalized = issue.strip().lower().replace("fails for", "failing when")
    summary = f"Issue related to {normalized}."
    return {"summary": summary}


# classify_severity, diagnose_issue, propose_fix, review_code were removed.
# Use functions/stubs.py for deterministic stubs with the modern (dict -> dict) signature.
