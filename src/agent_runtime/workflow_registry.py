from __future__ import annotations

"""File: src/agent_runtime/workflow_registry.py

Purpose:
Index workflow definitions by id/version and resolve references.

Description:
Scans workflow directories, registers validated workflows, and resolves
either explicit versions or latest numeric `vN` versions on demand.

Key Components:
- `WorkflowRegistry`
- `WorkflowReference` and `parse_workflow_reference`

Dependencies:
- `pathlib`, regex, workflow loader

Inputs/Outputs:
- Input: directory roots and workflow refs like `id@v2`
- Output: workflow dictionaries for execution

Side Effects:
- Reads workflow files during directory scan.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional
import re

from .errors import WorkflowValidationError
from .workflow import load_workflow


_VERSION_RE = re.compile(r"^v(\d+)$")


@dataclass(frozen=True)
class WorkflowReference:
    """Parsed workflow reference containing id and optional version.

    Example:
        >>> WorkflowReference(workflow_id="a", version="v1").workflow_id
        'a'
    """
    workflow_id: str
    version: Optional[str]


class WorkflowRegistry:
    """In-memory registry keyed by workflow id and version.

    The registry enforces uniqueness and supports latest-version lookup
    for CLI references that omit an explicit version.
    """

    def __init__(self) -> None:
        """Initialize empty workflow registry."""
        self._workflows: Dict[str, Dict[str, Dict[str, object]]] = {}

    @classmethod
    def from_directory(cls, root: str, handler_registry=None) -> "WorkflowRegistry":
        # TODO(M6-medium): handler_registry parameter is accepted but never
        #   forwarded to load_workflow() or parse_workflow(). Dead parameter.
        #   Remove once model steps are fully deprecated (see M1, M7).
        """Load versioned workflows from a directory tree.

        Files lacking `workflow.version` are skipped to avoid ambiguity.

        Example:
            >>> isinstance(WorkflowRegistry.from_directory("."), WorkflowRegistry)
            True
        """
        registry = cls()
        root_path = Path(root)
        if not root_path.exists():
            return registry

        for path in sorted(root_path.rglob("*.y*ml")):
            workflow = load_workflow(str(path))
            workflow_version = workflow.get("workflow_version")
            if workflow_version is None:
                continue
            registry.register(workflow)

        return registry

    def register(self, workflow: Dict[str, object]) -> None:
        """Register one parsed workflow dictionary.

        Raises:
            WorkflowValidationError: If id/version missing or duplicate.
        """
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
        """Resolve workflow by id and optional version.

        When version is omitted, latest numeric `vN` is selected.
        Raises validation error for unknown id/version combinations.
        """
        versions = self._workflows.get(workflow_id)
        if not versions:
            raise WorkflowValidationError(f"Workflow id not found: {workflow_id}")

        resolved_version = version or self.get_latest_version(workflow_id)
        workflow = versions.get(resolved_version)
        if workflow is None:
            raise WorkflowValidationError(f"Workflow version not found: {workflow_id}@{resolved_version}")
        return workflow

    def get_latest_version(self, workflow_id: str) -> str:
        """Return latest numeric version string for a workflow id.

        Version values must match `vN` format to keep ordering stable.
        """
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
    """Parse references like `workflow_id` or `workflow_id@v2`.

    Example:
        >>> parse_workflow_reference("triage@v2").version
        'v2'
    """
    if "@" not in value:
        return WorkflowReference(workflow_id=value, version=None)

    workflow_id, version = value.rsplit("@", 1)
    if not workflow_id or not version:
        raise WorkflowValidationError(f"Invalid workflow reference: {value}")
    return WorkflowReference(workflow_id=workflow_id, version=version)
