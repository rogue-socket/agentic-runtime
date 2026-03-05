class RuntimeErrorBase(Exception):
    """Base class for runtime errors."""


class WorkflowValidationError(RuntimeErrorBase):
    """Raised when workflow YAML is invalid."""


class StepExecutionError(RuntimeErrorBase):
    """Raised when a step fails to execute."""


class ToolNotFoundError(RuntimeErrorBase):
    """Raised when a tool is not found in registry."""


class HandlerNotFoundError(RuntimeErrorBase):
    """Raised when a step handler is not found in registry."""


class BranchResolutionError(RuntimeErrorBase):
    """Raised when branch resolution fails."""


class RunNotFoundError(RuntimeErrorBase):
    """Raised when a run id does not exist."""


class ReplayDataMissingError(RuntimeErrorBase):
    """Raised when required replay data is missing."""


class ReplayMismatchError(RuntimeErrorBase):
    """Raised when replayed state diverges from recorded state."""
