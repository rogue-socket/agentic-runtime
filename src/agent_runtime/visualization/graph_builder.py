from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..state import RuntimeState
from ..utils import safe_eval
from .run_loader import RunVisualizationData


@dataclass
class BranchDecision:
    step_id: str
    condition: str
    result: bool
    goto: str
    selected: bool


@dataclass
class GraphNode:
    step_id: str
    step_type: str
    status: str
    attempts: int
    duration_ms: Optional[int]
    execution_index: Optional[int]


@dataclass
class GraphEdge:
    source: str
    target: str
    kind: str


@dataclass
class GraphView:
    nodes: List[GraphNode]
    edges: List[GraphEdge]
    branch_decisions: List[BranchDecision]


class GraphBuilder:
    def build(self, data: RunVisualizationData) -> GraphView:
        executed_ids = [step.step_id for step in data.steps]
        executed_set = set(executed_ids)

        nodes: List[GraphNode] = []
        for step in data.steps:
            nodes.append(
                GraphNode(
                    step_id=step.step_id,
                    step_type=step.step_type,
                    status=step.status,
                    attempts=step.attempt_count or 1,
                    duration_ms=step.duration_ms,
                    execution_index=step.execution_index,
                )
            )

        for step_id in data.step_order:
            if step_id in executed_set:
                continue
            meta = data.step_meta.get(step_id)
            nodes.append(
                GraphNode(
                    step_id=step_id,
                    step_type=meta.step_type if meta else "unknown",
                    status="SKIPPED",
                    attempts=0,
                    duration_ms=None,
                    execution_index=None,
                )
            )

        edges: List[GraphEdge] = []
        for idx in range(len(executed_ids) - 1):
            edges.append(GraphEdge(source=executed_ids[idx], target=executed_ids[idx + 1], kind="executed"))

        branch_decisions: List[BranchDecision] = []
        step_lookup = {step.step_id: step for step in data.steps}
        for idx, step_id in enumerate(executed_ids):
            meta = data.step_meta.get(step_id)
            if not meta or not meta.next_rules:
                continue
            state = step_lookup[step_id].state_after or {}
            selected = executed_ids[idx + 1] if idx + 1 < len(executed_ids) else None
            for rule in meta.next_rules:
                if rule.is_default:
                    branch_decisions.append(
                        BranchDecision(
                            step_id=step_id,
                            condition="default",
                            result=selected == rule.goto,
                            goto=rule.goto,
                            selected=selected == rule.goto,
                        )
                    )
                    continue
                result = False
                try:
                    result = safe_eval(rule.when or "False", state)
                except Exception:
                    # [SCAFFOLD:DETERMINISM] Visualization branch eval best-effort; execution-time decision is source of truth.
                    result = False
                branch_decisions.append(
                    BranchDecision(
                        step_id=step_id,
                        condition=rule.when or "",
                        result=result,
                        goto=rule.goto,
                        selected=selected == rule.goto,
                    )
                )
            if selected:
                edges.append(GraphEdge(source=step_id, target=selected, kind="branch"))

        nodes.sort(key=lambda n: ((n.execution_index is None), n.execution_index if n.execution_index is not None else 10**9, n.step_id))
        return GraphView(nodes=nodes, edges=edges, branch_decisions=branch_decisions)


class StateDiffBuilder:
    @staticmethod
    def diff(before: Dict[str, Any], after: Dict[str, Any]) -> List[Dict[str, Any]]:
        return RuntimeState.diff_paths(before, after)
