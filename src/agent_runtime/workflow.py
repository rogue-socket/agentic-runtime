from __future__ import annotations

from typing import Any, Dict, List
import yaml

from .core import RetryPolicy, StepDefinition
from .errors import WorkflowValidationError
from .steps import StepHandlerRegistry
from .utils import sha256_text


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
        raw_text = f.read()
        raw = yaml.safe_load(raw_text)

    if not isinstance(raw, dict):
        raise WorkflowValidationError("Workflow YAML must be a mapping.")
    if "name" not in raw or not isinstance(raw["name"], str):
        raise WorkflowValidationError("Workflow must include a name.")
    if "steps" not in raw or not isinstance(raw["steps"], list):
        raise WorkflowValidationError("Workflow must include a steps list.")
    on_error = raw.get("on_error", "fail_fast")
    if on_error not in {"fail_fast", "continue"}:
        raise WorkflowValidationError("on_error must be fail_fast or continue.")

    steps: List[StepDefinition] = []
    for step in raw["steps"]:
        if not isinstance(step, dict):
            raise WorkflowValidationError("Each step must be a mapping.")
        _validate_step(step)
        step_type = step["type"]
        retry_cfg = step.get("retry")
        retry = None
        if retry_cfg is not None:
            if not isinstance(retry_cfg, dict):
                raise WorkflowValidationError("retry must be a mapping.")
            attempts = retry_cfg.get("attempts", 0)
            delay_seconds = retry_cfg.get("delay_seconds", 0)
            if not isinstance(attempts, int) or attempts < 0:
                raise WorkflowValidationError("retry.attempts must be a non-negative int.")
            if not isinstance(delay_seconds, (int, float)) or delay_seconds < 0:
                raise WorkflowValidationError("retry.delay_seconds must be non-negative.")
            retry = RetryPolicy(attempts=attempts, delay_seconds=float(delay_seconds))

        if step_type == "model":
            handler = handler_registry.get(step["handler"])
            steps.append(
                StepDefinition(
                    step_id=step["id"],
                    step_type="model",
                    handler=handler,
                    retry=retry,
                )
            )
        else:
            steps.append(
                StepDefinition(
                    step_id=step["id"],
                    step_type="tool",
                    tool_name=step["tool"],
                    raw_input=step.get("input"),
                    retry=retry,
                )
            )

    workflow_hash = sha256_text(raw_text)
    return {"name": raw["name"], "steps": steps, "on_error": on_error, "workflow_hash": workflow_hash}
