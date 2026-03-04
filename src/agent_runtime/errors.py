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
