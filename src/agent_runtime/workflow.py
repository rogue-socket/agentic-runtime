from __future__ import annotations

from typing import Any, Dict, List
import yaml

from .core import StepDefinition
from .errors import WorkflowValidationError
from .steps import StepHandlerRegistry


def _validate_step(step: Dict[str, Any]) -> None:
    if "id" not in step or not isinstance(step["id"], str):
        raise WorkflowValidationError("Each step must have a string id.")
    if "type" not in step or step["type"] not in {"model", "tool"}:
        raise WorkflowValidationError("Each step must have type: model or tool.")
    if step["type"] == "model" and "handler" not in step:
        raise WorkflowValidationError("Model steps must include handler.")
    if step["type"] == "tool" and "tool" not in step:
        raise WorkflowValidationError("Tool steps must include tool.")


def load_workflow(path: str, handler_registry: StepHandlerRegistry) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise WorkflowValidationError("Workflow YAML must be a mapping.")
    if "name" not in raw or not isinstance(raw["name"], str):
        raise WorkflowValidationError("Workflow must include a name.")
    if "steps" not in raw or not isinstance(raw["steps"], list):
        raise WorkflowValidationError("Workflow must include a steps list.")

    steps: List[StepDefinition] = []
    for step in raw["steps"]:
        if not isinstance(step, dict):
            raise WorkflowValidationError("Each step must be a mapping.")
        _validate_step(step)
        step_type = step["type"]
        if step_type == "model":
            handler = handler_registry.get(step["handler"])
            steps.append(
                StepDefinition(
                    step_id=step["id"],
                    step_type="model",
                    handler=handler,
                )
            )
        else:
            steps.append(
                StepDefinition(
                    step_id=step["id"],
                    step_type="tool",
                    tool_name=step["tool"],
                    raw_input=step.get("input"),
                )
            )

    return {"name": raw["name"], "steps": steps}
