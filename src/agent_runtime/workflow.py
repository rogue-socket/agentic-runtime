from __future__ import annotations

from typing import Any, Dict, List
import yaml

from .core import NextRule, RetryPolicy, StepDefinition
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
    if "inputs" in step and not isinstance(step["inputs"], dict):
        raise WorkflowValidationError("Step inputs must be a mapping.")
    if "next" in step and not isinstance(step["next"], list):
        raise WorkflowValidationError("Step next must be a list of rules.")


def _parse_workflow(raw_text: str, handler_registry: StepHandlerRegistry) -> Dict[str, Any]:
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
    step_ids: List[str] = []
    for step in raw["steps"]:
        if not isinstance(step, dict):
            raise WorkflowValidationError("Each step must be a mapping.")
        _validate_step(step)
        step_type = step["type"]
        if step["id"] in step_ids:
            raise WorkflowValidationError(f"Duplicate step id: {step['id']}")
        step_ids.append(step["id"])
        retry_cfg = step.get("retry")
        retry = None
        if retry_cfg is not None:
            if not isinstance(retry_cfg, dict):
                raise WorkflowValidationError("retry must be a mapping.")
            attempts = retry_cfg.get("attempts", 1)
            backoff = retry_cfg.get("backoff", "fixed")
            initial_delay = retry_cfg.get("initial_delay", 0)
            if not isinstance(attempts, int) or attempts < 1:
                raise WorkflowValidationError("retry.attempts must be >= 1.")
            if backoff not in {"fixed", "exponential"}:
                raise WorkflowValidationError("retry.backoff must be fixed or exponential.")
            if not isinstance(initial_delay, (int, float)) or initial_delay < 0:
                raise WorkflowValidationError("retry.initial_delay must be non-negative.")
            retry = RetryPolicy(
                attempts=attempts,
                backoff=backoff,
                initial_delay=float(initial_delay),
            )

        next_rules = None
        if "next" in step:
            rules = step["next"]
            default_count = 0
            next_rules = []
            for rule in rules:
                if not isinstance(rule, dict):
                    raise WorkflowValidationError("Each next rule must be a mapping.")
                if "default" in rule:
                    default_count += 1
                    if not isinstance(rule["default"], str):
                        raise WorkflowValidationError("next.default must be a string.")
                    next_rules.append(NextRule(when=None, goto=rule["default"], is_default=True))
                else:
                    if "when" not in rule or "goto" not in rule:
                        raise WorkflowValidationError("Each next rule must include when and goto.")
                    if not isinstance(rule["when"], str):
                        raise WorkflowValidationError("next.when must be a string.")
                    if not isinstance(rule["goto"], str):
                        raise WorkflowValidationError("next.goto must be a string.")
                    next_rules.append(NextRule(when=rule["when"], goto=rule["goto"], is_default=False))
            if default_count > 1:
                raise WorkflowValidationError("Only one default rule is allowed.")

        if step_type == "model":
            handler = handler_registry.get(step["handler"])
            steps.append(
                StepDefinition(
                    step_id=step["id"],
                    step_type="model",
                    handler=handler,
                    retry=retry,
                    input_spec=step.get("inputs"),
                    next_rules=next_rules,
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
                    input_spec=step.get("inputs"),
                    next_rules=next_rules,
                )
            )

    for rule_set in [s.next_rules for s in steps if s.next_rules]:
        for rule in rule_set:
            if rule.goto not in step_ids:
                raise WorkflowValidationError(f"next.goto target not found: {rule.goto}")

    workflow_hash = sha256_text(raw_text)
    return {
        "name": raw["name"],
        "steps": steps,
        "on_error": on_error,
        "workflow_hash": workflow_hash,
        "workflow_yaml": raw_text,
        "workflow_steps": [step.step_id for step in steps],
    }


def load_workflow(path: str, handler_registry: StepHandlerRegistry) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        raw_text = f.read()
    return _parse_workflow(raw_text, handler_registry)


def load_workflow_from_text(raw_text: str, handler_registry: StepHandlerRegistry) -> Dict[str, Any]:
    return _parse_workflow(raw_text, handler_registry)
