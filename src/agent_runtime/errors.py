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
