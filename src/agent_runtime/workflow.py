from __future__ import annotations

"""File: src/agent_runtime/workflow.py

Purpose:
Load and validate workflow YAML definitions into runtime step objects.

Description:
Transforms raw YAML into `StepDefinition` instances with validated retry,
branch, and contract metadata, then returns runtime-ready workflow data.

Key Components:
- `_parse_workflow` core parser
- `_validate_step` schema checks
- identity extraction and load helpers

Dependencies:
- `yaml`, core dataclasses

Inputs/Outputs:
- Input: workflow file path or raw YAML text
- Output: normalized workflow dictionary consumed by CLI/executor

Side Effects:
- Reads workflow files from disk in `load_workflow`.
"""

from typing import Any, Dict, List, Optional, Tuple
import yaml

from .core import NextRule, RetryPolicy, StepDefinition
from .errors import WorkflowValidationError
from .utils import sha256_text

# Valid step types for workflow steps
# [Pain Point Solved] #1 Spaghetti Orchestration: Declarative YAML separates workflow
#   topology (what connects to what) from execution (how each step runs).
# [Pain Point Solved] #6 Mixing Deterministic & Non-Deterministic Steps: Three distinct
#   step types — agent (LLM), function (pure Python), tool (external I/O) — each with
#   its own dispatch path, so you don't force everything through an LLM abstraction.
# [Pain Point Solved] #9 Collaboration Impossible: The workflow is a readable YAML file,
#   not imperative Python. A teammate can understand the pipeline in 10 seconds.
VALID_STEP_TYPES = {"agent", "function", "tool"}


def _validate_step(step: Dict[str, Any]) -> None:
    """Validate one raw step mapping.

    Ensures required fields by type and verifies optional field shapes
    for inputs/outputs/branch rules before object construction.

    Example:
        >>> _validate_step({"id": "a", "type": "agent", "agent": "reviewer"})
        >>> _validate_step({"id": "b", "type": "tool", "tool": "tools.echo"})
        >>> _validate_step({"id": "c", "type": "function", "function": "format_markdown"})
    """
    if "id" not in step or not isinstance(step["id"], str):
        raise WorkflowValidationError("Each step must have a string id.")
    if "type" not in step or step["type"] not in VALID_STEP_TYPES:
        raise WorkflowValidationError(
            f"Each step must have type: {', '.join(sorted(VALID_STEP_TYPES))}."
        )
    if step["type"] == "agent" and "agent" not in step:
        raise WorkflowValidationError("Agent steps must include 'agent' reference.")
    if step["type"] == "agent" and not isinstance(step["agent"], str):
        raise WorkflowValidationError("Agent step 'agent' must be a string (agent id).")
    if step["type"] == "function" and "function" not in step:
        raise WorkflowValidationError("Function steps must include 'function' reference.")
    if step["type"] == "function" and not isinstance(step["function"], str):
        raise WorkflowValidationError("Function step 'function' must be a string.")
    if step["type"] == "tool" and "tool" not in step:
        raise WorkflowValidationError("Tool steps must include tool.")
    if "inputs" in step and not isinstance(step["inputs"], (dict, list)):
        raise WorkflowValidationError("Step inputs must be a mapping or list.")
    if "inputs" in step and isinstance(step["inputs"], list):
        if not all(isinstance(v, str) for v in step["inputs"]):
            raise WorkflowValidationError("Step inputs list must contain only strings.")
    if "outputs" in step:
        if not isinstance(step["outputs"], list) or not all(isinstance(v, str) for v in step["outputs"]):
            raise WorkflowValidationError("Step outputs must be a list of strings.")
    if "next" in step and not isinstance(step["next"], list):
        raise WorkflowValidationError("Step next must be a list of rules.")


def _extract_workflow_identity(raw: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    """Extract workflow id/version from modern or legacy schema.

    Supports `workflow.id` + `workflow.version` and legacy `name` for
    backwards compatibility with older sample/tests.

    Example:
        >>> _extract_workflow_identity({"workflow": {"id": "w", "version": "v1"}})
        ('w', 'v1')
    """
    workflow_meta = raw.get("workflow")
    if workflow_meta is not None:
        if not isinstance(workflow_meta, dict):
            raise WorkflowValidationError("workflow must be a mapping when provided.")
        workflow_id = workflow_meta.get("id")
        workflow_version = workflow_meta.get("version")
        if not isinstance(workflow_id, str) or not workflow_id.strip():
            raise WorkflowValidationError("workflow.id must be a non-empty string.")
        if not isinstance(workflow_version, str) or not workflow_version.strip():
            raise WorkflowValidationError("workflow.version must be a non-empty string.")
        return workflow_id, workflow_version

    # Backward compatibility for older workflow files.
    legacy_name = raw.get("name")
    if not isinstance(legacy_name, str) or not legacy_name.strip():
        raise WorkflowValidationError("Workflow must include workflow.id/version or a legacy name.")
    return legacy_name, None


def _parse_inputs(raw_inputs: Any) -> Dict[str, Dict[str, Any]]:
    """Parse the workflow-level ``inputs:`` declaration.

    Supports two formats:

    List of strings (all required, no defaults)::

        inputs:
          - issue
          - priority

    Mapping with optional metadata::

        inputs:
          issue:
            description: "The issue text"
            required: true
          priority:
            description: "Priority level"
            required: false
            default: "medium"
    """
    inputs: Dict[str, Dict[str, Any]] = {}
    if isinstance(raw_inputs, list):
        for item in raw_inputs:
            if not isinstance(item, str):
                raise WorkflowValidationError("inputs list items must be strings.")
            inputs[item] = {"required": True}
    elif isinstance(raw_inputs, dict):
        for name, spec in raw_inputs.items():
            if not isinstance(name, str) or not name.strip():
                raise WorkflowValidationError("Input names must be non-empty strings.")
            if spec is None:
                inputs[name] = {"required": True}
            elif isinstance(spec, dict):
                inputs[name] = {
                    "description": spec.get("description", ""),
                    "required": spec.get("required", "default" not in spec),
                    "default": spec.get("default"),
                }
            else:
                raise WorkflowValidationError(
                    f"Input spec for '{name}' must be a mapping or null."
                )
    else:
        raise WorkflowValidationError("inputs must be a list or mapping.")
    return inputs


def _infer_inputs(raw_steps: List[Dict[str, Any]]) -> set:
    """Infer available input names by scanning step input specs for ``inputs.X`` references."""
    found: set = set()
    for step in raw_steps:
        spec = step.get("inputs")
        if isinstance(spec, dict):
            for value in spec.values():
                if isinstance(value, str) and value.startswith("inputs."):
                    parts = value.split(".")
                    if len(parts) >= 2:
                        found.add(parts[1])
    return found


def _parse_workflow(
    raw_text: str,
    *,
    functions_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Parse raw workflow YAML into runtime execution metadata.

    This performs structural validation, resolves functions,
    parses retry and branch rules, validates contracts, and computes
    workflow hash.

    Example:
        >>> wf = _parse_workflow("name: w\\nsteps:\\n  - id: a\\n    type: tool\\n    tool: tools.echo\\n")
        >>> wf["workflow_id"]
        'w'
    """
    raw = yaml.safe_load(raw_text)

    if not isinstance(raw, dict):
        raise WorkflowValidationError("Workflow YAML must be a mapping.")
    if "steps" not in raw or not isinstance(raw["steps"], list):
        raise WorkflowValidationError("Workflow must include a steps list.")
    workflow_id, workflow_version = _extract_workflow_identity(raw)

    on_error = raw.get("on_error", "fail_fast")
    if on_error not in {"fail_fast", "continue"}:
        raise WorkflowValidationError("on_error must be fail_fast or continue.")

    # --- Parse workflow-level input declarations ---
    raw_inputs_block = raw.get("inputs")
    legacy_contract = raw.get("inputs_contract")
    if raw_inputs_block is not None:
        workflow_inputs = _parse_inputs(raw_inputs_block)
        available_inputs = set(workflow_inputs.keys())
    elif legacy_contract is not None:
        if not isinstance(legacy_contract, list) or not all(isinstance(v, str) for v in legacy_contract):
            raise WorkflowValidationError("inputs_contract must be a list of strings.")
        workflow_inputs = {name: {"required": True} for name in legacy_contract}
        available_inputs = set(legacy_contract)
    else:
        workflow_inputs = {}
        available_inputs = _infer_inputs(raw["steps"])

    steps: List[StepDefinition] = []
    step_ids: List[str] = []
    produced_by: Dict[str, str] = {}
    seen_steps: List[str] = []
    for step in raw["steps"]:
        if not isinstance(step, dict):
            raise WorkflowValidationError("Each step must be a mapping.")
        _validate_step(step)
        step_type = step["type"]
        if step["id"] in step_ids:
            raise WorkflowValidationError(f"Duplicate step id: {step['id']}")
        step_ids.append(step["id"])
        seen_steps.append(step["id"])
        timeout_ms = step.get("timeout_ms")
        if timeout_ms is not None and (not isinstance(timeout_ms, int) or timeout_ms < 0):
            raise WorkflowValidationError("timeout_ms must be a non-negative integer.")

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

        input_spec = step.get("inputs")
        input_contract = None
        if isinstance(input_spec, list):
            input_contract = list(input_spec)
            mapped: Dict[str, str] = {}
            for key in input_contract:
                if key in produced_by:
                    mapped[key] = f"steps.{produced_by[key]}.{key}"
                elif key in available_inputs:
                    mapped[key] = f"inputs.{key}"
                else:
                    raise WorkflowValidationError(
                        f"Step {step['id']} input contract key '{key}' is unavailable (missing or produced in future)."
                    )
            input_spec = mapped
        elif isinstance(input_spec, dict):
            for value in input_spec.values():
                if isinstance(value, str) and value.startswith("steps."):
                    parts = value.split(".")
                    if len(parts) < 2:
                        raise WorkflowValidationError(f"Invalid step input path: {value}")
                    referenced_step = parts[1]
                    if referenced_step not in seen_steps[:-1]:
                        raise WorkflowValidationError(
                            f"Step {step['id']} references future/unknown step output: {value}"
                        )

        output_contract = step.get("outputs")
        if output_contract:
            for output_key in output_contract:
                if output_key in produced_by:
                    raise WorkflowValidationError(
                        f"Output contract collision: key '{output_key}' already produced by step '{produced_by[output_key]}'"
                    )
                produced_by[output_key] = step["id"]

        if step_type == "agent":
            agent_ref = step["agent"]
            # parse optional version pinning: "code_reviewer@v2"
            agent_id = agent_ref
            agent_version = None
            if "@" in agent_ref:
                agent_id, agent_version = agent_ref.rsplit("@", 1)
            steps.append(
                StepDefinition(
                    step_id=step["id"],
                    step_type="agent",
                    agent_id=agent_id,
                    agent_version=agent_version,
                    retry=retry,
                    input_spec=input_spec if isinstance(input_spec, dict) else None,
                    input_contract=input_contract,
                    output_contract=output_contract,
                    next_rules=next_rules,
                    timeout_ms=timeout_ms,
                )
            )
        elif step_type == "function":
            func_ref = step["function"]
            # Resolve function at parse time (fail fast)
            func_callable = None
            if functions_dir:
                from .function_resolver import resolve_function
                func_callable = resolve_function(func_ref, functions_dir)
            steps.append(
                StepDefinition(
                    step_id=step["id"],
                    step_type="function",
                    function_ref=func_ref,
                    function_callable=func_callable,
                    retry=retry,
                    input_spec=input_spec if isinstance(input_spec, dict) else None,
                    input_contract=input_contract,
                    output_contract=output_contract,
                    next_rules=next_rules,
                    timeout_ms=timeout_ms,
                )
            )
        else:  # tool
            steps.append(
                StepDefinition(
                    step_id=step["id"],
                    step_type="tool",
                    tool_name=step["tool"],
                    raw_input=step.get("input"),
                    retry=retry,
                    input_spec=input_spec if isinstance(input_spec, dict) else None,
                    input_contract=input_contract,
                    output_contract=output_contract,
                    next_rules=next_rules,
                    timeout_ms=timeout_ms,
                )
            )

    for rule_set in [s.next_rules for s in steps if s.next_rules]:
        for rule in rule_set:
            if rule.goto not in step_ids:
                raise WorkflowValidationError(f"next.goto target not found: {rule.goto}")

    workflow_hash = sha256_text(raw_text)
    return {
        "workflow_id": workflow_id,
        "workflow_version": workflow_version,
        "inputs": workflow_inputs,
        "steps": steps,
        "on_error": on_error,
        "workflow_hash": workflow_hash,
        "workflow_yaml": raw_text,
        "workflow_steps": [step.step_id for step in steps],
    }


def load_workflow(
    path: str,
    *,
    functions_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Load workflow YAML from file path and parse it.

    Example:
        >>> isinstance(load_workflow, object)
        True
    """
    with open(path, "r", encoding="utf-8") as f:
        raw_text = f.read()
    return _parse_workflow(raw_text, functions_dir=functions_dir)


def load_workflow_from_text(
    raw_text: str,
    *,
    functions_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Parse workflow from in-memory YAML text.

    Useful for tests and replay/inspect flows where workflow YAML is
    stored in the database instead of read from filesystem.

    Example:
        >>> load_workflow_from_text("name: w\\nsteps:\\n  - id: a\\n    type: tool\\n    tool: tools.echo\\n")["workflow_id"]
        'w'
    """
    return _parse_workflow(raw_text, functions_dir=functions_dir)
