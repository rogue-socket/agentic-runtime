"""File: src/agent_runtime/errors.py

Purpose:
Centralize custom exception types used by the runtime.

Description:
Defines domain-specific errors so callers can distinguish validation,
execution, replay, and lookup failures without parsing generic messages.

Key Components:
- `RuntimeErrorBase` hierarchy with specialized subclasses

Dependencies:
- Python exception system only

Inputs/Outputs:
- Input: raised by runtime modules
- Output: typed failures for CLI/tests and API consumers

Side Effects:
- None.
"""

from typing import Dict, Tuple, Type

class RuntimeErrorBase(Exception):
    """Root runtime exception.

    This provides a shared parent type for all runtime-specific errors.
    Catch it when callers want to handle runtime failures generically.

    Example:
        >>> raise RuntimeErrorBase("runtime failure")
        >>> isinstance(RuntimeErrorBase("x"), Exception)
        True
    """


class WorkflowValidationError(RuntimeErrorBase):
    """Raised when workflow definitions fail structural or semantic checks.

    The loader raises this for invalid step schemas, duplicate IDs, and
    invalid branch/retry/workflow metadata fields.

    Example:
        >>> raise WorkflowValidationError("bad workflow")
        >>> isinstance(WorkflowValidationError("x"), RuntimeErrorBase)
        True
    """


class StepExecutionError(RuntimeErrorBase):
    """Raised when a runtime step cannot complete successfully.

    Common triggers include handler failures, contract violations, and
    branch resolution errors propagated at execution time.

    Example:
        >>> raise StepExecutionError("step failed")
        >>> isinstance(StepExecutionError("x"), RuntimeErrorBase)
        True
    """


class ToolNotFoundError(RuntimeErrorBase):
    """Raised when a requested tool name is missing in the registry.

    This typically indicates missing tool registration in CLI bootstrap
    or an invalid `tool:` reference in workflow YAML.

    Example:
        >>> raise ToolNotFoundError("tool missing")
        >>> isinstance(ToolNotFoundError("x"), RuntimeErrorBase)
        True
    """


class BranchResolutionError(RuntimeErrorBase):
    """Raised when no branch rule matches and no default exists.

    This protects deterministic execution by failing explicitly instead of
    silently picking an arbitrary next step.

    Example:
        >>> raise BranchResolutionError("no branch matched")
        >>> isinstance(BranchResolutionError("x"), RuntimeErrorBase)
        True
    """


class RunNotFoundError(RuntimeErrorBase):
    """Raised when storage lookup cannot find a run id.

    Replay and inspect style operations use this to distinguish missing
    data from malformed replay records.

    Example:
        >>> raise RunNotFoundError("missing run")
        >>> isinstance(RunNotFoundError("x"), RuntimeErrorBase)
        True
    """


class ReplayDataMissingError(RuntimeErrorBase):
    """Raised when stored replay artifacts are incomplete.

    Triggered when a run has missing step history or missing before/after
    state snapshots required for deterministic reconstruction.

    Example:
        >>> raise ReplayDataMissingError("missing history")
        >>> isinstance(ReplayDataMissingError("x"), RuntimeErrorBase)
        True
    """


class ReplayMismatchError(RuntimeErrorBase):
    """Raised when replayed state diverges from recorded state."""


class WorkflowIntegrityError(RuntimeErrorBase):
    """Raised when a workflow has been modified since the original run."""


class AgentValidationError(RuntimeErrorBase):
    """Raised when an agent definition is invalid."""


class ConfigValidationError(RuntimeErrorBase):
    """Raised when runtime configuration is invalid."""


class StorageValidationError(RuntimeErrorBase):
    """Raised when storage schema/version checks fail."""


_ERROR_TAXONOMY: Dict[Type[BaseException], Tuple[str, str]] = {
    WorkflowValidationError: (
        "AR-WORKFLOW-VALIDATION",
        "Workflow definition is invalid. Check workflow schema, step fields, and references.",
    ),
    StepExecutionError: (
        "AR-STEP-EXECUTION",
        "A workflow step failed during execution. Inspect run steps for the failing step and error details.",
    ),
    ToolNotFoundError: (
        "AR-TOOL-NOT-FOUND",
        "Referenced tool is not registered. Verify tool name and runtime tools directory configuration.",
    ),
    BranchResolutionError: (
        "AR-BRANCH-RESOLUTION",
        "Branch conditions did not resolve to a valid next step. Check next rules and defaults in workflow YAML.",
    ),
    RunNotFoundError: (
        "AR-RUN-NOT-FOUND",
        "Run id was not found in storage. Verify run id and selected database path.",
    ),
    ReplayDataMissingError: (
        "AR-REPLAY-DATA-MISSING",
        "Run cannot be replayed because required step/state history is missing.",
    ),
    ReplayMismatchError: (
        "AR-REPLAY-MISMATCH",
        "Replay verification found state drift. The stored run history may be inconsistent.",
    ),
    WorkflowIntegrityError: (
        "AR-WORKFLOW-INTEGRITY",
        "Workflow definition changed after run start. Resume is blocked to preserve determinism.",
    ),
    AgentValidationError: (
        "AR-AGENT-VALIDATION",
        "Agent definition is invalid. Check agent schema, required fields, and prompt references.",
    ),
    ConfigValidationError: (
        "AR-CONFIG-VALIDATION",
        "Runtime configuration is invalid. Check runtime.yaml schema and values.",
    ),
    StorageValidationError: (
        "AR-STORAGE-VALIDATION",
        "Storage schema/version is incompatible with this runtime.",
    ),
    FileNotFoundError: (
        "AR-FILE-NOT-FOUND",
        "A required file was not found. Verify path and working directory.",
    ),
    ValueError: (
        "AR-VALUE-ERROR",
        "An input or stored value is invalid for this command.",
    ),
    RuntimeError: (
        "AR-RUNTIME-ERROR",
        "Runtime operation failed unexpectedly. Inspect logs and step details.",
    ),
    Exception: (
        "AR-UNEXPECTED",
        "Unexpected runtime failure. Inspect logs and run details for root cause.",
    ),
}


def get_error_info(exc: BaseException) -> Tuple[str, str]:
    """Resolve stable error code and user-facing remediation message."""
    for cls in type(exc).mro():
        if cls in _ERROR_TAXONOMY:
            return _ERROR_TAXONOMY[cls]
    return _ERROR_TAXONOMY[Exception]


def get_error_code(exc: BaseException) -> str:
    """Return stable error code for an exception."""
    return get_error_info(exc)[0]


def get_user_message(exc: BaseException) -> str:
    """Return user-facing remediation message for an exception."""
    return get_error_info(exc)[1]
