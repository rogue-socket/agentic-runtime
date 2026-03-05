from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import yaml

from ..core import Run, StepExecution
from ..storage.base import Storage


@dataclass
class WorkflowRule:
    when: Optional[str]
    goto: str
    is_default: bool


@dataclass
class WorkflowStepMeta:
    step_id: str
    step_type: str
    tool_name: Optional[str]
    next_rules: List[WorkflowRule]


@dataclass
class RunVisualizationData:
    run: Run
    steps: List[StepExecution]
    latest_state: Dict[str, Any]
    initial_state: Dict[str, Any]
    step_meta: Dict[str, WorkflowStepMeta]
    step_order: List[str]


class RunLoader:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    def load(self, run_id: str) -> RunVisualizationData:
        run = self.storage.load_run(run_id)
        steps = self.storage.load_steps(run_id)
        latest_state = self.storage.load_latest_state(run_id)
        initial_state = self.storage.load_initial_state(run_id)

        step_meta: Dict[str, WorkflowStepMeta] = {}
        step_order: List[str] = []

        if run.workflow_yaml:
            raw = yaml.safe_load(run.workflow_yaml) or {}
            for raw_step in raw.get("steps", []):
                if not isinstance(raw_step, dict):
                    continue
                step_id = raw_step.get("id")
                if not isinstance(step_id, str):
                    continue
                step_order.append(step_id)
                next_rules: List[WorkflowRule] = []
                for raw_rule in raw_step.get("next", []) or []:
                    if not isinstance(raw_rule, dict):
                        continue
                    if "default" in raw_rule and isinstance(raw_rule["default"], str):
                        next_rules.append(WorkflowRule(when=None, goto=raw_rule["default"], is_default=True))
                    elif isinstance(raw_rule.get("when"), str) and isinstance(raw_rule.get("goto"), str):
                        next_rules.append(
                            WorkflowRule(when=raw_rule["when"], goto=raw_rule["goto"], is_default=False)
                        )
                step_meta[step_id] = WorkflowStepMeta(
                    step_id=step_id,
                    step_type=str(raw_step.get("type", "unknown")),
                    tool_name=raw_step.get("tool") if isinstance(raw_step.get("tool"), str) else None,
                    next_rules=next_rules,
                )

        if not step_order:
            step_order = [step.step_id for step in steps]

        return RunVisualizationData(
            run=run,
            steps=steps,
            latest_state=latest_state,
            initial_state=initial_state,
            step_meta=step_meta,
            step_order=step_order,
        )
