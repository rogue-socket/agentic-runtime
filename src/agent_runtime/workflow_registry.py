from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional
import re

from .errors import WorkflowValidationError
from .steps import StepHandlerRegistry
from .workflow import load_workflow


_VERSION_RE = re.compile(r"^v(\d+)$")


@dataclass(frozen=True)
class WorkflowReference:
    workflow_id: str
    version: Optional[str]


class WorkflowRegistry:
    def __init__(self) -> None:
        self._workflows: Dict[str, Dict[str, Dict[str, object]]] = {}

    @classmethod
    def from_directory(cls, root: str, handler_registry: StepHandlerRegistry) -> "WorkflowRegistry":
        registry = cls()
        root_path = Path(root)
        if not root_path.exists():
            return registry

        for path in sorted(root_path.rglob("*.y*ml")):
            workflow = load_workflow(str(path), handler_registry)
            workflow_version = workflow.get("workflow_version")
            if workflow_version is None:
                continue
            registry.register(workflow)

        return registry

    def register(self, workflow: Dict[str, object]) -> None:
        workflow_id = workflow.get("workflow_id")
        workflow_version = workflow.get("workflow_version")
        if not isinstance(workflow_id, str) or not workflow_id:
            raise WorkflowValidationError("workflow_id missing while registering workflow.")
        if not isinstance(workflow_version, str) or not workflow_version:
            raise WorkflowValidationError(f"workflow_version missing for workflow '{workflow_id}'.")

        versions = self._workflows.setdefault(workflow_id, {})
        if workflow_version in versions:
            raise WorkflowValidationError(f"Duplicate workflow version: {workflow_id}@{workflow_version}")
        versions[workflow_version] = workflow

    def get(self, workflow_id: str, version: Optional[str] = None) -> Dict[str, object]:
        versions = self._workflows.get(workflow_id)
        if not versions:
            raise WorkflowValidationError(f"Workflow id not found: {workflow_id}")

        resolved_version = version or self.get_latest_version(workflow_id)
        workflow = versions.get(resolved_version)
        if workflow is None:
            raise WorkflowValidationError(f"Workflow version not found: {workflow_id}@{resolved_version}")
        return workflow

    def get_latest_version(self, workflow_id: str) -> str:
        versions = self._workflows.get(workflow_id)
        if not versions:
            raise WorkflowValidationError(f"Workflow id not found: {workflow_id}")

        version_keys = list(versions.keys())
        numeric_versions = []
        for version in version_keys:
            match = _VERSION_RE.match(version)
            if match is None:
                raise WorkflowValidationError(
                    f"Unsupported workflow version format for latest resolution: {workflow_id}@{version}. Expected vN."
                )
            numeric_versions.append((int(match.group(1)), version))

        numeric_versions.sort(key=lambda item: item[0])
        return numeric_versions[-1][1]


def parse_workflow_reference(value: str) -> WorkflowReference:
    if "@" not in value:
        return WorkflowReference(workflow_id=value, version=None)

    workflow_id, version = value.rsplit("@", 1)
    if not workflow_id or not version:
        raise WorkflowValidationError(f"Invalid workflow reference: {value}")
    return WorkflowReference(workflow_id=workflow_id, version=version)
