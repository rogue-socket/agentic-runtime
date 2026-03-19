"""Example handler module.

The runtime auto-discovers handlers from the handlers/ directory.

Two conventions are supported:

1. Zero-config: every public function (not starting with _) is registered
   using the function name as the handler name.

2. Explicit: define a __handlers__ dict mapping handler names to functions.
   This gives you full control over naming and lets you skip helper functions.

This file uses convention 1 (zero-config). Both functions below will be
automatically available as handlers in workflow YAML.
"""

from agent_runtime.state import RuntimeState


def example_handler(state: RuntimeState) -> dict:
    """Example handler that echoes back the input with a prefix.

    Usage in workflow YAML:
        - id: my_step
          type: model
          handler: example_handler
          inputs:
            message: inputs.message
    """
    # TODO: Replace with real logic (e.g. LLM call).
    message = state.get("message", "")
    return {"result": f"Processed: {message}"}


# --- To use explicit convention instead, uncomment below and remove the
# --- public function above:
#
# def _my_internal_helper():
#     pass
#
# def _my_handler(state):
#     return {"result": "hello"}
#
# __handlers__ = {
#     "my_handler": _my_handler,
# }
