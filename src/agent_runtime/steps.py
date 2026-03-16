from __future__ import annotations

"""File: src/agent_runtime/steps.py

Purpose:
Define model-step handler registration and default scaffold handler(s).

Description:
Provides a lightweight registry mapping handler names to callables and
ships `generate_summary` as a deterministic example model handler.

Key Components:
- `StepHandlerRegistry`
- `generate_summary`

Dependencies:
- RuntimeState wrapper and error types

Inputs/Outputs:
- Input: handler names and runtime step input states
- Output: structured dict outputs written into step namespaces

Side Effects:
- None.
"""

from typing import Any, Callable, Dict

from .errors import HandlerNotFoundError
from .state import RuntimeState

StateDict = Dict[str, Any]
StepHandler = Callable[[RuntimeState], StateDict]


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
