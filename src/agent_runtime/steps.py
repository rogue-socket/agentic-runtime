from __future__ import annotations

from typing import Any, Callable, Dict

from .errors import HandlerNotFoundError

StateDict = Dict[str, Any]
StepHandler = Callable[[StateDict], StateDict]


class StepHandlerRegistry:
    def __init__(self) -> None:
        self._handlers: Dict[str, StepHandler] = {}

    def register(self, name: str, handler: StepHandler) -> None:
        self._handlers[name] = handler

    def get(self, name: str) -> StepHandler:
        if name not in self._handlers:
            raise HandlerNotFoundError(f"Handler not found: {name}")
        return self._handlers[name]


def generate_summary(state: StateDict) -> StateDict:
    # [SCAFFOLD:LLM] Replace deterministic summary with model-backed generation.
    if "issue" not in state:
        raise KeyError("Missing required key: issue")
    issue = state["issue"]
    if not isinstance(issue, str) or not issue.strip():
        raise ValueError("issue must be a non-empty string")

    normalized = issue.strip().lower().replace("fails for", "failing when")
    summary = f"Issue related to {normalized}."
    return {"summary": summary}
